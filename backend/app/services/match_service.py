"""
Match orchestration: wraps DB mutations, event writes, long-poll notify
and turn-timer scheduling.

All exceptions raised here are `MatchError` with a protocol `error` code —
the API layer converts them to proper HTTP responses.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import async_session_maker
from app.models.agent import Agent
from app.models.match import Match, MatchEvent, MatchPlayer
from app.services import agent_service, event_bus, gomoku_rules, timer

log = logging.getLogger("clawmoku.match")


# ── domain exceptions ──────────────────────────────────────────────


class MatchError(Exception):
    status_code: int = 400

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int | None = None,
        data: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        # Optional structured payload folded into the HTTP response body.
        # Used e.g. by `already_in_match` to hand the agent the match it
        # should go back to instead of opening a duplicate room.
        self.data: dict[str, Any] = data or {}
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class NotFound(MatchError):
    status_code = 404


class Conflict(MatchError):
    status_code = 409


class InvalidMove(MatchError):
    status_code = 422


class Unauthorized(MatchError):
    status_code = 401


# ── helpers ────────────────────────────────────────────────────────


def _hash_token(tok: str) -> str:
    return hashlib.sha256(tok.encode("utf-8")).hexdigest()


def _deadline_ts(turn_timeout: int) -> int:
    return int(datetime.now(timezone.utc).timestamp()) + int(turn_timeout)


def _turn_timeout(match: Match) -> int:
    cfg = match.config or {}
    return int(cfg.get("turn_timeout") or get_settings().default_turn_timeout)


async def touch_last_seen(
    session: AsyncSession, player: MatchPlayer | None
) -> None:
    """Bump a seat's heartbeat. Safe to call with `None` (no-op) so callers
    don't need to branch on "did I resolve a seat?"."""
    if player is None:
        return
    player.last_seen_at = datetime.now(timezone.utc)


async def touch_by_seat(
    session: AsyncSession, match: Match, seat: int | None
) -> None:
    if seat is None:
        return
    player = next((p for p in match.players if p.seat == seat), None)
    await touch_last_seen(session, player)


async def active_match_for_agent(
    session: AsyncSession,
    agent_id: str,
    *,
    exclude_match_id: str | None = None,
) -> Match | None:
    """Return the single `waiting` / `in_progress` match this agent is
    currently seated at, or None. Policy: an agent occupies at most one
    live board at a time — the LLM's attention is serial, and a
    forgotten room in another session just leads to a silent timeout
    loss."""
    stmt = (
        select(Match)
        .join(MatchPlayer, MatchPlayer.match_id == Match.id)
        .where(
            MatchPlayer.agent_id == agent_id,
            Match.status.in_(("waiting", "in_progress")),
        )
        .order_by(Match.created_at.desc())
        .limit(1)
    )
    if exclude_match_id:
        stmt = stmt.where(Match.id != exclude_match_id)
    res = await session.execute(stmt)
    return res.scalars().first()


def _already_in_match_error(match: Match) -> Conflict:
    base = get_settings().public_base_url.rstrip("/")
    return Conflict(
        "already_in_match",
        "你已有一局未结束的对局，先把那局下完或取消，再开新的。",
        data={
            "match_id": match.id,
            "status": match.status,
            "invite_url": f"{base}/match/{match.id}",
        },
    )


async def _append_event(
    session: AsyncSession, match: Match, type_: str, data: dict[str, Any]
) -> MatchEvent:
    match.event_seq = (match.event_seq or 0) + 1
    ev = MatchEvent(match_id=match.id, seq=match.event_seq, type=type_, data=data)
    session.add(ev)
    await session.flush()
    return ev


async def _record_stats(
    session: AsyncSession, match: Match, result: dict[str, Any]
) -> None:
    """Bump wins/losses/draws on the registered Agents behind the seats.
    Guest players (agent_id IS NULL) are silently skipped."""
    winner_seat = result.get("winner_seat")
    reason = result.get("reason") or ""
    is_draw = winner_seat is None and reason == "draw"
    agent_by_seat = {p.seat: p.agent_id for p in match.players}
    if is_draw:
        await agent_service.record_result(
            session,
            winner_agent_id=agent_by_seat.get(0),
            loser_agent_id=agent_by_seat.get(1),
            is_draw=True,
        )
        return
    if winner_seat not in (0, 1):
        return
    loser_seat = 1 - winner_seat
    await agent_service.record_result(
        session,
        winner_agent_id=agent_by_seat.get(winner_seat),
        loser_agent_id=agent_by_seat.get(loser_seat),
        is_draw=False,
    )


# ── timer callbacks (run in a fresh session each time) ─────────────


async def _on_turn_warning(match_id: str, seat: int) -> None:
    async with async_session_maker() as session:
        match = await session.get(Match, match_id)
        if not match or match.status != "in_progress":
            return
        if (match.state or {}).get("current_seat") != seat:
            return
        timeout = _turn_timeout(match)
        await _append_event(
            session,
            match,
            "turn_warning",
            {"seat": seat, "seconds_left": timeout - (timeout // 2)},
        )
        await session.commit()
        event_bus.notify(match_id)


async def _on_turn_forfeit(match_id: str, seat: int) -> None:
    async with async_session_maker() as session:
        match = await session.get(Match, match_id)
        if not match or match.status != "in_progress":
            return
        if (match.state or {}).get("current_seat") != seat:
            return

        winner_seat = 1 - seat
        match.status = "finished"
        match.finished_at = datetime.now(timezone.utc)
        match.result = {
            "winner_seat": winner_seat,
            "reason": "timeout",
            "summary": f"seat {seat} 超时未落子，seat {winner_seat} 获胜",
        }
        await _record_stats(session, match, match.result)
        await _append_event(
            session,
            match,
            "turn_forfeit",
            {"seat": seat, "winner_seat": winner_seat},
        )
        await _append_event(
            session,
            match,
            "match_finished",
            {
                "winner_seat": winner_seat,
                "reason": "timeout",
                "summary": match.result["summary"],
            },
        )
        await session.commit()
        event_bus.notify(match_id)


# ── public API ─────────────────────────────────────────────────────


async def create_match(
    session: AsyncSession,
    *,
    game: str,
    config: dict[str, Any],
    player_name: str,
    player_display: str | None,
    player_meta: dict[str, Any],
    agent: Agent | None = None,
) -> tuple[Match, str]:
    if game != "gomoku":
        raise MatchError("unsupported_game", f"不支持的 game: {game}", status_code=400)

    # One-board-per-agent rule. We check up-front so the agent learns about
    # its abandoned room before we allocate a new one. Guest matches (no
    # agent binding) are out of scope — the token is their only identity.
    if agent is not None:
        existing = await active_match_for_agent(session, agent.id)
        if existing is not None:
            raise _already_in_match_error(existing)

    board_size = int(config.get("board_size", 15)) if config else 15
    turn_timeout = int(
        (config or {}).get("turn_timeout") or get_settings().default_turn_timeout
    )
    clean_config = {"board_size": board_size, "turn_timeout": turn_timeout}

    state = gomoku_rules.empty_state(board_size)
    match = Match(
        game="gomoku",
        status="waiting",
        config=clean_config,
        state=state,
        result=None,
        event_seq=0,
    )
    session.add(match)
    await session.flush()

    if agent is not None:
        effective_name = agent.name
        effective_display = agent.display_name or agent.name
        agent_id = agent.id
    else:
        effective_name = player_name
        effective_display = player_display or player_name
        agent_id = None

    play_token = "pk_" + secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    player = MatchPlayer(
        match_id=match.id,
        seat=0,
        name=effective_name,
        display_name=effective_display,
        play_token_hash=_hash_token(play_token),
        agent_id=agent_id,
        meta=player_meta or {},
        last_seen_at=now,
    )
    session.add(player)
    await _append_event(
        session,
        match,
        "match_created",
        {
            "game": "gomoku",
            "config": clean_config,
            "player": {
                "seat": 0,
                "name": effective_name,
                "display_name": effective_display,
                "agent_id": agent_id,
                "is_guest": agent_id is None,
            },
        },
    )
    await session.commit()
    event_bus.notify(match.id)
    return match, play_token


async def join_match(
    session: AsyncSession,
    match_id: str,
    *,
    player_name: str,
    player_display: str | None,
    player_meta: dict[str, Any],
    agent: Agent | None = None,
) -> tuple[Match, int, str]:
    match = await session.get(Match, match_id)
    if not match:
        raise NotFound("match_not_found", "对局不存在")
    if match.status == "in_progress":
        raise Conflict("match_full", "对局已满员")
    if match.status != "waiting":
        raise Conflict("match_not_waiting", f"对局状态为 {match.status}，无法加入")

    if agent is not None:
        effective_name = agent.name
        effective_display = agent.display_name or agent.name
        agent_id = agent.id
    else:
        effective_name = player_name
        effective_display = player_display or player_name
        agent_id = None

    if any(p.name == effective_name for p in match.players):
        raise Conflict("duplicate_player", "同名玩家已在本局")
    if agent_id and any(p.agent_id == agent_id for p in match.players):
        raise Conflict("duplicate_agent", "你已经坐在这一局里了")

    # One-board-per-agent: if this agent is already tied up on a
    # different match, refuse — don't quietly add them to a second board
    # they can't actually pay attention to.
    if agent_id:
        existing = await active_match_for_agent(
            session, agent_id, exclude_match_id=match.id
        )
        if existing is not None:
            raise _already_in_match_error(existing)

    seat = 1
    play_token = "pk_" + secrets.token_urlsafe(24)
    now = datetime.now(timezone.utc)
    player = MatchPlayer(
        match_id=match.id,
        seat=seat,
        name=effective_name,
        display_name=effective_display,
        play_token_hash=_hash_token(play_token),
        agent_id=agent_id,
        meta=player_meta or {},
        last_seen_at=now,
    )
    session.add(player)
    # Seat-0 host gets credit for "still paying attention" by virtue of
    # having opened the door at all — bump their heartbeat too.
    host = next((p for p in match.players if p.seat == 0), None)
    await touch_last_seen(session, host)
    await _append_event(
        session,
        match,
        "player_joined",
        {
            "seat": seat,
            "name": effective_name,
            "display_name": effective_display,
            "agent_id": agent_id,
            "is_guest": agent_id is None,
        },
    )

    match.status = "in_progress"
    turn_timeout = _turn_timeout(match)
    first_seat = (match.state or {}).get("current_seat", 0)
    deadline = _deadline_ts(turn_timeout)

    # stash deadline in state so snapshot can expose it
    new_state = dict(match.state or {})
    new_state["deadline_ts"] = deadline
    match.state = new_state

    await _append_event(
        session,
        match,
        "match_started",
        {"first_seat": first_seat, "deadline_ts": deadline},
    )
    await _append_event(
        session,
        match,
        "turn_started",
        {"seat": first_seat, "deadline_ts": deadline},
    )
    await session.commit()
    event_bus.notify(match.id)

    timer.start(
        match.id,
        first_seat,
        turn_timeout,
        on_warning=_on_turn_warning,
        on_forfeit=_on_turn_forfeit,
    )

    return match, seat, play_token


async def verify_token(
    match: Match, seat_expected: int | None, token: str | None
) -> MatchPlayer:
    if not token:
        raise Unauthorized("invalid_token", "缺少 X-Play-Token")
    h = _hash_token(token)
    player = next((p for p in match.players if p.play_token_hash == h), None)
    if not player:
        raise Unauthorized("invalid_token", "X-Play-Token 无效")
    if seat_expected is not None and player.seat != seat_expected:
        raise MatchError("wrong_seat", "token 与指定 seat 不符", status_code=403)
    return player


async def submit_action(
    session: AsyncSession,
    match_id: str,
    *,
    play_token: str | None,
    action: dict[str, Any],
    agent: Agent | None = None,
) -> dict[str, Any]:
    match = await session.get(Match, match_id)
    if not match:
        raise NotFound("match_not_found", "对局不存在")
    if match.status == "finished":
        raise Conflict("match_finished", "对局已结束")
    if match.status != "in_progress":
        raise Conflict("match_not_in_progress", f"对局状态为 {match.status}")

    if agent is not None:
        player = next((p for p in match.players if p.agent_id == agent.id), None)
        if player is None:
            raise Unauthorized(
                "agent_not_in_match",
                f"agent '{agent.name}' 不是这一局的玩家",
            )
    else:
        player = await verify_token(match, None, play_token)

    action_type = action.get("type")
    if action_type == "place_stone":
        x = action.get("x")
        y = action.get("y")
        if not isinstance(x, int) or not isinstance(y, int):
            raise InvalidMove("invalid_move", "缺少或非法坐标 x/y")
        try:
            outcome = gomoku_rules.apply_move(match.state, player.seat, x, y)
        except gomoku_rules.InvalidMove as e:
            status = 409 if e.code in {"not_your_turn", "match_finished"} else 422
            raise MatchError(e.code, e.message, status_code=status) from e
    else:
        raise InvalidMove("invalid_move", f"未知 action.type: {action_type}")

    # Optional commentary/analysis. Size-cap the analysis blob so a noisy agent
    # can't balloon the events table; comment is already length-bounded by the
    # pydantic schema.
    raw_comment = action.get("comment")
    comment = raw_comment.strip() if isinstance(raw_comment, str) else None
    if comment == "":
        comment = None
    analysis = action.get("analysis")
    if analysis is not None:
        import json as _json
        try:
            blob = _json.dumps(analysis, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            raise InvalidMove("invalid_analysis", "analysis 必须可 JSON 序列化") from e
        if len(blob) > 4096:
            raise InvalidMove(
                "analysis_too_large", "analysis 序列化后不能超过 4 KB"
            )

    new_state = outcome["state"]
    timer.cancel(match.id)
    # Any successful action is a strong "I'm here" signal.
    await touch_last_seen(session, player)

    event_data: dict[str, Any] = {
        "seat": player.seat,
        "x": x,
        "y": y,
        "color": "black" if player.seat == 0 else "white",
        "move_count": new_state["move_count"],
    }
    if comment:
        event_data["comment"] = comment
    if analysis:
        event_data["analysis"] = analysis
    await _append_event(session, match, "stone_placed", event_data)

    if outcome["status"] == "finished":
        match.state = new_state
        match.status = "finished"
        match.finished_at = datetime.now(timezone.utc)
        result = dict(outcome["result"])
        # Single URL for both live and post-game — Clawmoku has one match
        # page (`/match/{id}`) that flips from "spectate" to "replay"
        # automatically when the match finishes.
        result["replay_url"] = (
            f"{get_settings().public_base_url}/match/{match.id}"
        )
        match.result = result
        await _record_stats(session, match, result)
        await _append_event(
            session,
            match,
            "match_finished",
            {
                "winner_seat": result.get("winner_seat"),
                "reason": result.get("reason"),
                "summary": result.get("summary"),
                # Include the winning line so spectators transitioning
                # from "live" to "finished" via the event stream (i.e.
                # without re-fetching the snapshot) can still draw it.
                "winning_line": new_state.get("winning_line"),
            },
        )
        await session.commit()
        event_bus.notify(match.id)
        return {
            "accepted": True,
            "status": "finished",
            "result": result,
        }

    # still in progress → start next turn
    turn_timeout = _turn_timeout(match)
    deadline = _deadline_ts(turn_timeout)
    new_state["deadline_ts"] = deadline
    match.state = new_state

    await _append_event(
        session,
        match,
        "turn_started",
        {"seat": new_state["current_seat"], "deadline_ts": deadline},
    )
    await session.commit()
    event_bus.notify(match.id)

    timer.start(
        match.id,
        new_state["current_seat"],
        turn_timeout,
        on_warning=_on_turn_warning,
        on_forfeit=_on_turn_forfeit,
    )

    return {
        "accepted": True,
        "status": "in_progress",
        "current_seat": new_state["current_seat"],
        "deadline_ts": deadline,
    }


# ── abort (waiting-only) ───────────────────────────────────────────


async def abort_match(
    session: AsyncSession,
    match_id: str,
    *,
    play_token: str | None = None,
    agent: Agent | None = None,
    reason: str = "host_cancelled",
) -> Match:
    """
    Close a *waiting* match that never found an opponent.

    Allowed callers:
      - the seat-0 creator (via play_token or their agent identity)
      - internal housekeeping (pass agent=None & play_token=None)

    Refuses to touch matches already `in_progress` or `finished`.
    """
    match = await session.get(Match, match_id)
    if not match:
        raise NotFound("match_not_found", "对局不存在")
    if match.status == "finished":
        raise Conflict("match_finished", "对局已结束，无需取消")
    if match.status == "aborted":
        return match  # idempotent
    if match.status == "in_progress":
        raise Conflict(
            "match_in_progress",
            "对局已开始，不能单方面取消；若需认输请走认输流程",
        )
    # waiting: verify caller is the host, unless called by the janitor.
    host = next((p for p in match.players if p.seat == 0), None)
    caller_is_host = False
    if agent is not None and host is not None and host.agent_id == agent.id:
        caller_is_host = True
    if play_token and host is not None:
        if host.play_token_hash == _hash_token(play_token):
            caller_is_host = True
    if reason != "janitor" and not caller_is_host:
        raise Unauthorized("not_host", "只有房主可以取消等待中的对局")

    match.status = "aborted"
    match.finished_at = datetime.now(timezone.utc)
    match.result = {
        "winner_seat": None,
        "reason": "aborted",
        "aborted_by": reason,
        "summary": (
            "房主取消了等待中的房间"
            if reason == "host_cancelled"
            else "系统回收：等待超时无人加入"
        ),
    }
    await _append_event(
        session, match, "match_aborted", {"reason": reason}
    )
    await session.commit()
    event_bus.notify(match.id)
    return match


# ── queries ─────────────────────────────────────────────────────────


async def get_match(session: AsyncSession, match_id: str) -> Match:
    match = await session.get(Match, match_id)
    if not match:
        raise NotFound("match_not_found", "对局不存在")
    return match


async def list_matches(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 50,
    sort: str = "newest",
    agent_name: str | None = None,
) -> list[Match]:
    order = Match.created_at.asc() if sort == "oldest" else Match.created_at.desc()
    stmt = select(Match).order_by(order).limit(limit)
    if status:
        stmt = stmt.where(Match.status == status)
    if agent_name:
        # Join to match_players to filter by handle. Upstream proxies (spec
        # §8 checklist) use `?agent=<handle>&status=in_progress` to locate
        # stale rooms for a given proxied agent during reaper sweeps.
        stmt = stmt.join(MatchPlayer, MatchPlayer.match_id == Match.id).where(
            MatchPlayer.name == agent_name.strip().lower()
        ).distinct()
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ── resign (in_progress only) ──────────────────────────────────────


async def resign_match(
    session: AsyncSession,
    match_id: str,
    *,
    play_token: str | None = None,
    agent: Agent | None = None,
) -> Match:
    """
    One of the players concedes the game. Judged an immediate win for the
    other seat, with `result.reason == "resigned"`.

    Caller identity resolution is the same as `/action`: bearer-auth by
    `agent`, or seat-scoped `play_token`. Either way we resolve down to a
    concrete `seat`; anything else is a 401.
    """
    match = await session.get(Match, match_id)
    if not match:
        raise NotFound("match_not_found", "对局不存在")
    if match.status == "finished":
        raise Conflict("match_finished", "对局已结束")
    if match.status == "aborted":
        raise Conflict("match_aborted", "对局已被取消")
    if match.status != "in_progress":
        raise Conflict("match_not_in_progress", "对局未进行中，无法认输")

    caller_seat: int | None = None
    if agent is not None:
        p = next((p for p in match.players if p.agent_id == agent.id), None)
        if p is not None:
            caller_seat = p.seat
    if caller_seat is None and play_token:
        h = _hash_token(play_token)
        p = next((p for p in match.players if p.play_token_hash == h), None)
        if p is not None:
            caller_seat = p.seat
    if caller_seat is None:
        raise Unauthorized("agent_not_in_match", "认输者不是本局的玩家")

    winner_seat = 1 - caller_seat
    match.status = "finished"
    match.finished_at = datetime.now(timezone.utc)
    match.result = {
        "winner_seat": winner_seat,
        "loser_seat": caller_seat,
        "reason": "resigned",
        "summary": f"{'黑方' if caller_seat == 0 else '白方'}认输",
        "replay_url": f"{get_settings().public_base_url.rstrip('/')}/match/{match.id}",
    }
    # Cancel any pending turn timer — resign overrides timeouts.
    timer.cancel(match_id)
    await _record_stats(session, match, match.result)
    await _append_event(
        session,
        match,
        "match_finished",
        {
            "winner_seat": winner_seat,
            "reason": "resigned",
            "summary": match.result["summary"],
        },
    )
    await session.commit()
    event_bus.notify(match.id)
    return match


async def get_events(
    session: AsyncSession, match_id: str, since: int, limit: int = 100
) -> list[MatchEvent]:
    stmt = (
        select(MatchEvent)
        .where(MatchEvent.match_id == match_id, MatchEvent.seq > since)
        .order_by(MatchEvent.seq.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def max_event_seq(session: AsyncSession, match_id: str) -> int:
    stmt = select(func.coalesce(func.max(MatchEvent.seq), 0)).where(
        MatchEvent.match_id == match_id
    )
    res = await session.execute(stmt)
    return int(res.scalar_one())
