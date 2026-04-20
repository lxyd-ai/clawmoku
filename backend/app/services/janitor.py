"""
Background housekeeping task.

Currently handles one chore:
  - Auto-abort `waiting` matches whose host never attracted an opponent within
    `settings.waiting_max_minutes`. Without this, orphan rooms would pile up
    in the lobby forever.

The loop lives for the lifetime of the FastAPI app and is cancelled on shutdown.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import async_session_maker
from app.models.match import Match
from app.services import match_service

log = logging.getLogger("clawmoku.janitor")


async def _sweep_once() -> int:
    settings = get_settings()
    max_minutes = settings.waiting_max_minutes
    if max_minutes <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_minutes)
    swept = 0
    async with async_session_maker() as session:
        stmt = (
            select(Match)
            .where(Match.status == "waiting", Match.created_at < cutoff)
            .limit(200)
        )
        rows = (await session.execute(stmt)).scalars().all()
        for m in rows:
            try:
                await match_service.abort_match(
                    session, m.id, reason="janitor"
                )
                swept += 1
            except Exception as e:  # noqa: BLE001
                log.warning("janitor failed to abort %s: %r", m.id, e)
    if swept:
        log.info("janitor auto-aborted %d stale waiting match(es)", swept)
    return swept


async def run() -> None:
    """Forever-loop; invoked as a lifespan task."""
    settings = get_settings()
    interval = max(5, int(settings.janitor_interval_sec))
    log.info(
        "janitor started (interval=%ds, waiting_max=%dmin)",
        interval,
        settings.waiting_max_minutes,
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
