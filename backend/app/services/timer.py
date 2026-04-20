"""
Per-match turn-deadline watcher.

Design:
- `match_service.start_turn_timer(match_id, seat, timeout)` cancels any running
  timer for the match and schedules a new one.
- When the timer hits `timeout/2` it emits a `turn_warning` event.
- When it hits `timeout` it emits `turn_forfeit` + `match_finished`
  (opponent wins).
- Any new move cancels the timer before scheduling the next.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

log = logging.getLogger("clawmoku.timer")

_timers: dict[str, asyncio.Task] = {}


def cancel(match_id: str) -> None:
    t = _timers.pop(match_id, None)
    if t and not t.done():
        t.cancel()


def _run(
    match_id: str,
    seat: int,
    timeout: int,
    warn_at: int,
    on_warning: Callable[[str, int], Awaitable[Any]],
    on_forfeit: Callable[[str, int], Awaitable[Any]],
) -> asyncio.Task:
    async def loop():
        try:
            if warn_at < timeout:
                await asyncio.sleep(warn_at)
                try:
                    await on_warning(match_id, seat)
                except Exception:  # noqa: BLE001
                    log.exception("turn_warning callback failed")
                await asyncio.sleep(timeout - warn_at)
            else:
                await asyncio.sleep(timeout)
            try:
                await on_forfeit(match_id, seat)
            except Exception:  # noqa: BLE001
                log.exception("turn_forfeit callback failed")
        except asyncio.CancelledError:
            pass

    return asyncio.create_task(loop())


def start(
    match_id: str,
    seat: int,
    timeout: int,
    *,
    on_warning: Callable[[str, int], Awaitable[Any]],
    on_forfeit: Callable[[str, int], Awaitable[Any]],
) -> None:
    cancel(match_id)
    warn_at = max(1, timeout // 2)
    _timers[match_id] = _run(match_id, seat, timeout, warn_at, on_warning, on_forfeit)
