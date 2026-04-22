from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import optional_agent
from app.core.config import get_settings
from app.core.db import async_session_maker, get_db
from app.models.agent import Agent
from app.models.match import Match
from app.schemas.match import (
    ActionIn,
    CreateMatchIn,
    CreateMatchOut,
    EventOut,
    EventsOut,
    JoinMatchIn,
    JoinMatchOut,
    MatchListItem,
    MoveOut,
    MovesOut,
    PlayerOut,
    SnapshotOut,
)
from app.services import event_bus, gomoku_rules, match_service
from app.services.match_service import MatchError

router = APIRouter(prefix="/api", tags=["matches"])


def _error(exc: MatchError) -> HTTPException:
    detail: dict[str, Any] = {"error": exc.code, "message": exc.message}
    # Fold any structured payload (e.g. `already_in_match` → the match the
    # agent should return to) into the response so clients don't need to
    # parse the error message.
    if getattr(exc, "data", None):
        detail.update(exc.data)
    return HTTPException(status_code=exc.status_code, detail=detail)


def _player_out(p) -> PlayerOut:
    return PlayerOut(
        seat=p.seat,
        name=p.name,
        display_name=p.display_name,
        agent_id=p.agent_id,
        is_guest=p.agent_id is None,
        last_seen_at=p.last_seen_at.isoformat() if p.last_seen_at else None,
    )


def _snapshot(match: Match, your_seat: int | None = None) -> dict[str, Any]:
    state = match.state or {}
    render = gomoku_rules.render_snapshot(state)
    players = [_player_out(p).model_dump() for p in match.players]
    terminal = match.status in ("finished", "aborted")
    current_seat = state.get("current_seat") if not terminal else None
    your_turn = None
    if your_seat is not None and match.status == "in_progress":
        your_turn = state.get("current_seat") == your_seat
    return SnapshotOut(
        match_id=match.id,
        game=match.game,
        status=match.status,
        config=match.config or {},
        players=players,
        current_seat=current_seat,
        deadline_ts=state.get("deadline_ts") if match.status == "in_progress" else None,
        render=render,
        result=match.result,
        events_total=match.event_seq or 0,
        created_at=match.created_at.isoformat(),
        your_turn=your_turn,
    ).model_dump()


def _require_identity(
    agent: Agent | None, player_in, who: str
) -> tuple[str, str | None]:
    """Return (name, display_name) given auth context. `player_in` can be None."""
    if agent is not None:
        return agent.name, (agent.display_name or agent.name)
    if player_in is not None and player_in.name:
        return player_in.name, player_in.display_name
    raise HTTPException(
        status_code=400,
        detail={
            "error": "identity_required",
            "message": f"{who} 需要 Authorization: Bearer <api_key>，或在 body.player.name 中提供游客名",
        },
    )


# ── POST /api/matches ───────────────────────────────────────────────


@router.post("/matches", response_model=CreateMatchOut, status_code=201)
async def create_match(
    payload: CreateMatchIn,
    session: AsyncSession = Depends(get_db),
    agent: Agent | None = Depends(optional_agent),
):
    name, display = _require_identity(agent, payload.player, "创建对局")
    meta = (payload.player.meta if payload.player else None) or {}

    try:
        match, token = await match_service.create_match(
            session,
            game=payload.game,
            config=payload.config.model_dump(exclude_none=True),
            player_name=name,
            player_display=display,
            player_meta=meta,
            agent=agent,
        )
    except MatchError as e:
        raise _error(e) from e
    base = get_settings().public_base_url
    return CreateMatchOut(
        match_id=match.id,
        seat=0,
        play_token=token,
        status=match.status,
        config=match.config,
        invite_url=f"{base}/match/{match.id}",
    )


# ── POST /api/matches/{id}/join ────────────────────────────────────


@router.post("/matches/{match_id}/join", response_model=JoinMatchOut)
async def join_match(
    match_id: str,
    payload: JoinMatchIn,
    session: AsyncSession = Depends(get_db),
    agent: Agent | None = Depends(optional_agent),
):
    name, display = _require_identity(agent, payload.player, "加入对局")
    meta = (payload.player.meta if payload.player else None) or {}
    try:
        match, seat, token = await match_service.join_match(
            session,
            match_id,
            player_name=name,
            player_display=display,
            player_meta=meta,
            agent=agent,
        )
    except MatchError as e:
        raise _error(e) from e
    state = match.state or {}
    base = get_settings().public_base_url.rstrip("/")
    return JoinMatchOut(
        match_id=match.id,
        seat=seat,
        play_token=token,
        status=match.status,
        current_seat=state.get("current_seat", 0),
        deadline_ts=state.get("deadline_ts", 0),
        invite_url=f"{base}/match/{match.id}",
    )


# ── POST /api/matches/{id}/action ──────────────────────────────────


@router.post("/matches/{match_id}/action")
async def submit_action(
    match_id: str,
    payload: ActionIn,
    x_play_token: str | None = Header(default=None, alias="X-Play-Token"),
    session: AsyncSession = Depends(get_db),
    agent: Agent | None = Depends(optional_agent),
):
    if agent is None and not x_play_token:
        raise _error(
            MatchError(
                "auth_required",
                "需要 Authorization: Bearer <api_key> 或 X-Play-Token",
                status_code=401,
            )
        )
    try:
        result = await match_service.submit_action(
            session,
            match_id,
            play_token=x_play_token,
            action=payload.model_dump(),
            agent=agent,
        )
    except MatchError as e:
        raise _error(e) from e
    return result


# ── POST /api/matches/{id}/abort ───────────────────────────────────


@router.post("/matches/{match_id}/abort")
async def abort_match_endpoint(
    match_id: str,
    x_play_token: str | None = Header(default=None, alias="X-Play-Token"),
    session: AsyncSession = Depends(get_db),
    agent: Agent | None = Depends(optional_agent),
):
    """Host closes a `waiting` match that never got an opponent."""
    if agent is None and not x_play_token:
        raise _error(
            MatchError(
                "auth_required",
                "需要 Authorization: Bearer <api_key> 或 X-Play-Token",
                status_code=401,
            )
        )
    try:
        match = await match_service.abort_match(
            session,
            match_id,
            play_token=x_play_token,
            agent=agent,
            reason="host_cancelled",
        )
    except MatchError as e:
        raise _error(e) from e
    return {
        "match_id": match.id,
        "status": match.status,
        "result": match.result,
    }


# ── POST /api/matches/{id}/resign ──────────────────────────────────


@router.post("/matches/{match_id}/resign")
async def resign_match_endpoint(
    match_id: str,
    x_play_token: str | None = Header(default=None, alias="X-Play-Token"),
    session: AsyncSession = Depends(get_db),
    agent: Agent | None = Depends(optional_agent),
):
    """Player concedes an in-progress match. Immediate win for the other seat.

    See partner-spec v1 §2.9. Distinct from `/abort` (which is host-only,
    waiting-only, and doesn't assign a winner).
    """
    if agent is None and not x_play_token:
        raise _error(
            MatchError(
                "auth_required",
                "需要 Authorization: Bearer <api_key> 或 X-Play-Token",
                status_code=401,
            )
        )
    try:
        match = await match_service.resign_match(
            session,
            match_id,
            play_token=x_play_token,
            agent=agent,
        )
    except MatchError as e:
        raise _error(e) from e
    return {
        "match_id": match.id,
        "status": match.status,
        "result": match.result,
    }


# ── GET /api/matches/{id} ──────────────────────────────────────────


async def _resolve_seat(
    match: Match,
    explicit_seat: int | None,
    agent: Agent | None,
    play_token: str | None,
) -> int | None:
    """Best-effort resolution of the caller's seat from (query, agent, token)."""
    if explicit_seat is not None:
        return explicit_seat
    if agent is not None:
        player = next((p for p in match.players if p.agent_id == agent.id), None)
        if player is not None:
            return player.seat
    if play_token:
        try:
            player = await match_service.verify_token(match, None, play_token)
            return player.seat
        except MatchError:
            return None
    return None


def _wait_condition_met(
    match: Match, your_seat: int | None, wait_for: str
) -> bool:
    """True = long-poll should return immediately."""
    # Any terminal state should wake all pollers so callers can unwind cleanly.
    if match.status in ("finished", "aborted"):
        return True
    if wait_for == "opponent_joined":
        # We consider the door opened the moment the match leaves 'waiting'.
        return match.status != "waiting"
    if wait_for == "your_turn":
        if your_seat is None:
            # Caller has no identity bound → treat as any_change so we still
            # unblock and return a snapshot instead of hanging forever.
            return True
        state = match.state or {}
        return (
            match.status == "in_progress"
            and state.get("current_seat") == your_seat
        )
    # any_change or unknown → any notify wakes us; first check is always False
    return False


@router.get("/matches/{match_id}", response_model=SnapshotOut)
async def get_match(
    match_id: str,
    seat: int | None = Query(default=None, ge=0, le=1),
    wait: int = Query(
        default=0,
        ge=0,
        description="Long-poll seconds; 0 = no wait. Capped server-side.",
    ),
    wait_for: str = Query(
        default="any_change",
        pattern="^(any_change|your_turn|opponent_joined)$",
        description="Unblock condition for long-polling.",
    ),
    x_play_token: str | None = Header(default=None, alias="X-Play-Token"),
    session: AsyncSession = Depends(get_db),
    agent: Agent | None = Depends(optional_agent),
):
    try:
        match = await match_service.get_match(session, match_id)
    except MatchError as e:
        raise _error(e) from e

    your_seat = await _resolve_seat(match, seat, agent, x_play_token)

    # Heartbeat: if the caller resolved to a concrete seat, record that
    # they're actively observing this match. Skipped for finished /
    # aborted matches (no attendance-light to power). A spectator
    # without a bound seat also contributes nothing here.
    if your_seat is not None and match.status in ("waiting", "in_progress"):
        await match_service.touch_by_seat(session, match, your_seat)
        await session.commit()

    if wait <= 0 or _wait_condition_met(match, your_seat, wait_for):
        return _snapshot(match, your_seat)

    # ── long-poll loop ─────────────────────────────────────────────
    # IMPORTANT: release the request-scoped DB session before sleeping on the
    # event bus; holding it starves the connection pool under concurrent load
    # (e.g. one agent long-polling while the other tries to POST an action).
    import time as _time

    await session.close()

    max_wait = min(int(wait), get_settings().longpoll_max_wait)
    deadline = _time.monotonic() + max_wait
    while True:
        remaining = deadline - _time.monotonic()
        if remaining <= 0:
            break
        woken = await event_bus.wait_for_new(match_id, remaining)
        # Reopen a fresh, short-lived session to recheck condition.
        async with async_session_maker() as s2:
            try:
                match = await match_service.get_match(s2, match_id)
            except MatchError:
                break
            your_seat = await _resolve_seat(match, seat, agent, x_play_token)
            if _wait_condition_met(match, your_seat, wait_for):
                return _snapshot(match, your_seat)
        if not woken:
            break  # timed out without a matching change
        # Spurious wake (condition still unmet) → loop on remaining budget.

    # Final snapshot read with a fresh session.
    async with async_session_maker() as s3:
        match = await match_service.get_match(s3, match_id)
        your_seat = await _resolve_seat(match, seat, agent, x_play_token)
        return _snapshot(match, your_seat)


# ── GET /api/matches ───────────────────────────────────────────────


@router.get("/matches", response_model=list[MatchListItem])
async def list_matches(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    sort: str = Query(
        default="newest",
        pattern="^(newest|oldest)$",
        description="newest = latest first (default, good for lobby); "
        "oldest = longest-waiting first (handy for agents hunting "
        "for rooms that really need an opponent).",
    ),
    agent: str | None = Query(
        default=None,
        description="Filter to rooms where this handle is seated. Upstream "
        "proxies (partner-spec v1 §8) use `?agent=<handle>&status=in_progress` "
        "to reap stale rooms for a given proxied agent.",
    ),
    session: AsyncSession = Depends(get_db),
):
    from datetime import datetime, timezone

    matches = await match_service.list_matches(
        session, status=status, limit=limit, sort=sort, agent_name=agent
    )
    base = get_settings().public_base_url.rstrip("/")
    now = datetime.now(timezone.utc)
    out = []
    for m in matches:
        state = m.state or {}
        created = m.created_at
        # naive timestamps from SQLite → assume UTC
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        waited = max(0, int((now - created).total_seconds()))
        out.append(
            MatchListItem(
                match_id=m.id,
                status=m.status,
                players=[_player_out(p) for p in m.players],
                current_seat=state.get("current_seat") if m.status == "in_progress" else None,
                created_at=m.created_at.isoformat(),
                move_count=state.get("move_count", 0),
                waited_sec=waited,
                invite_url=f"{base}/match/{m.id}",
            )
        )
    return out


# ── GET /api/matches/{id}/moves ────────────────────────────────────


@router.get("/matches/{match_id}/moves", response_model=MovesOut)
async def get_moves(
    match_id: str,
    session: AsyncSession = Depends(get_db),
):
    """Flat, replay-friendly view of all placed stones including commentary."""
    try:
        match = await match_service.get_match(session, match_id)
    except MatchError as e:
        raise _error(e) from e

    events = await match_service.get_events(session, match_id, since=0, limit=10_000)
    moves: list[MoveOut] = []
    prev_ts: float | None = None
    move_number = 0
    # Use the match creation as baseline so the first move's spent_ms is
    # measured from when the second player joined (good enough approximation).
    for ev in events:
        if ev.type != "stone_placed":
            continue
        move_number += 1
        ts = ev.created_at
        ts_epoch = ts.timestamp()
        spent_ms = None
        if prev_ts is not None:
            spent_ms = int(max(0, (ts_epoch - prev_ts) * 1000))
        prev_ts = ts_epoch
        data = ev.data or {}
        seat = int(data.get("seat", 0))
        moves.append(
            MoveOut(
                seq=ev.seq,
                move_number=move_number,
                seat=seat,
                color="black" if seat == 0 else "white",
                x=int(data.get("x", 0)),
                y=int(data.get("y", 0)),
                ts=ts.isoformat(),
                spent_ms=spent_ms,
                comment=data.get("comment"),
                analysis=data.get("analysis"),
            )
        )

    return MovesOut(
        match_id=match.id,
        status=match.status,
        total_moves=len(moves),
        moves=moves,
        result=match.result,
        players=[_player_out(p) for p in match.players],
        config=match.config or {},
        created_at=match.created_at.isoformat(),
        finished_at=match.finished_at.isoformat() if match.finished_at else None,
    )


# ── GET /api/matches/{id}/events ───────────────────────────────────


@router.get("/matches/{match_id}/events", response_model=EventsOut)
async def get_events(
    match_id: str,
    since: int = Query(default=0, ge=0),
    wait: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    try:
        match = await match_service.get_match(session, match_id)
    except MatchError as e:
        raise _error(e) from e

    max_wait = min(wait, get_settings().longpoll_max_wait)

    events = await match_service.get_events(session, match_id, since=since)
    if not events and max_wait > 0 and match.status != "finished":
        await event_bus.wait_for_new(match_id, max_wait)
        await session.refresh(match)
        events = await match_service.get_events(session, match_id, since=since)

    next_since = events[-1].seq if events else since
    return EventsOut(
        match_id=match_id,
        since=since,
        next_since=next_since,
        events=[
            EventOut(
                seq=e.seq, type=e.type, data=e.data, ts=e.created_at.isoformat()
            )
            for e in events
        ],
        status=match.status,
    )
