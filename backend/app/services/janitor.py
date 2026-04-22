"""
Background housekeeping task.

Two overlapping reapers both operate on `waiting` matches:

  1. HARD CAP — any waiting match older than `waiting_max_minutes`
     (default 30 min) is aborted no matter what. Keeps pathological
     "host polls forever, no opponent ever comes" rooms from sticking
     around indefinitely.

  2. SOFT CAP — a waiting match whose *host* hasn't been observed
     (poll / action / abort) for `waiting_host_idle_minutes` (default
     5 min) is aborted even if the hard cap hasn't been hit. This is
     the important one in practice: agents that crash-exit or close
     their session mid-wait stop heart-beating, and we reap their
     orphan rooms within a few minutes instead of letting them clog
     the lobby for half an hour.

Both sweeps share the same abort path (`reason="janitor"`), so the
resulting `match_aborted` event looks identical to downstream
consumers.

The loop lives for the lifetime of the FastAPI app and is cancelled on
shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.config import get_settings
from app.core.db import async_session_maker
from app.models.match import Match, MatchPlayer
from app.services import match_service

log = logging.getLogger("clawmoku.janitor")


async def _sweep_once() -> int:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    hard_minutes = settings.waiting_max_minutes
    idle_minutes = settings.waiting_host_idle_minutes
    if hard_minutes <= 0 and idle_minutes <= 0:
        return 0

    # Candidate match ids: union of hard-cap and idle-host sweeps.
    candidates: dict[str, str] = {}  # match_id → reason tag

    async with async_session_maker() as session:
        # 1) Hard cap: old waiting matches regardless of heartbeat.
        if hard_minutes > 0:
            hard_cutoff = now - timedelta(minutes=hard_minutes)
            stmt = (
                select(Match.id)
                .where(
                    Match.status == "waiting",
                    Match.created_at < hard_cutoff,
                )
                .limit(200)
            )
            for mid in (await session.execute(stmt)).scalars().all():
                candidates[mid] = "hard_cap"

        # 2) Idle-host cap: seat-0 hasn't heart-beat within idle_cutoff.
        #    `last_seen_at IS NULL` is treated as "never observed", so we
        #    fall back to comparing against the row's joined_at (the
        #    moment the host created the match) — otherwise pre-migration
        #    rows would be reaped instantly.
        if idle_minutes > 0:
            idle_cutoff = now - timedelta(minutes=idle_minutes)
            stmt = (
                select(Match.id)
                .join(MatchPlayer, MatchPlayer.match_id == Match.id)
                .where(
                    Match.status == "waiting",
                    MatchPlayer.seat == 0,
                    or_(
                        MatchPlayer.last_seen_at < idle_cutoff,
                        # Pre-migration rows: no heartbeat yet. Use joined_at.
                        (MatchPlayer.last_seen_at.is_(None))
                        & (MatchPlayer.joined_at < idle_cutoff),
                    ),
                )
                .limit(200)
            )
            for mid in (await session.execute(stmt)).scalars().all():
                candidates.setdefault(mid, "host_idle")

        swept = 0
        for mid, tag in candidates.items():
            try:
                await match_service.abort_match(
                    session, mid, reason="janitor"
                )
                swept += 1
                log.info("janitor reaped waiting match %s (%s)", mid, tag)
            except Exception as e:  # noqa: BLE001
                log.warning("janitor failed to abort %s: %r", mid, e)
    if swept:
        log.info("janitor auto-aborted %d stale waiting match(es)", swept)
    return swept


async def run() -> None:
    """Forever-loop; invoked as a lifespan task."""
    settings = get_settings()
    interval = max(5, int(settings.janitor_interval_sec))
    log.info(
        "janitor started (interval=%ds, hard_cap=%dmin, host_idle=%dmin)",
        interval,
        settings.waiting_max_minutes,
        settings.waiting_host_idle_minutes,
    )
    while True:
        try:
            await _sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.exception("janitor sweep crashed: %r", e)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            log.info("janitor cancelled, exiting")
            raise
