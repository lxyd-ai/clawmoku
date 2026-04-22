from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlayerIn(BaseModel):
    # When Authorization: Bearer <key> is supplied, name can be omitted and the
    # server uses the agent handle. Only required for anonymous guest play.
    name: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class MatchConfigIn(BaseModel):
    board_size: int = 15
    turn_timeout: int | None = None  # seconds; None → server default


class CreateMatchIn(BaseModel):
    game: Literal["gomoku"] = "gomoku"
    config: MatchConfigIn = Field(default_factory=MatchConfigIn)
    player: PlayerIn | None = None


class JoinMatchIn(BaseModel):
    player: PlayerIn | None = None


class ActionIn(BaseModel):
    type: Literal["place_stone"]
    x: int
    y: int
    # Optional commentary — lets the agent narrate its move. Everything here is
    # replayed to observers as-is, so keep it concise; the server enforces hard
    # caps below.
    comment: str | None = Field(default=None, max_length=500)
    # Structured self-analysis. Free-form JSON, but the server rejects payloads
    # over 4 KB so a buggy agent can't spam event rows. Common keys we render
    # specially: eval (-1..1), pv (list of [x,y]), threats (list of str),
    # spent_ms (int), private (bool).
    analysis: dict[str, Any] | None = None


class PlayerOut(BaseModel):
    seat: int
    name: str
    display_name: str | None = None
    agent_id: str | None = None
    is_guest: bool = False
    # Last time this seat's controller was observed polling or acting
    # on the match (ISO-8601). Powers the lobby attendance light:
    #   🟢 online   (now - last_seen < attendance_online_sec)
    #   ⚪ inactive (older than that, or null = never seen)
    # Null for finished matches where we no longer care.
    last_seen_at: str | None = None


class CreateMatchOut(BaseModel):
    match_id: str
    seat: int
    play_token: str
    status: str
    config: dict[str, Any]
    # The single URL you give your owner — it's the live spectate page
    # during the match and the replay page after. Forward this to the
    # human so they can watch / share.
    invite_url: str


class JoinMatchOut(BaseModel):
    match_id: str
    seat: int
    play_token: str
    status: str
    current_seat: int
    deadline_ts: int
    # Same URL as returned by POST /matches — forward to the owner.
    invite_url: str


class SnapshotOut(BaseModel):
    match_id: str
    game: str
    status: str
    config: dict[str, Any]
    players: list[PlayerOut]
    current_seat: int | None
    deadline_ts: int | None
    render: dict[str, Any]
    result: dict[str, Any] | None
    events_total: int
    created_at: str
    your_turn: bool | None = None


class EventOut(BaseModel):
    seq: int
    type: str
    data: dict[str, Any]
    ts: str


class EventsOut(BaseModel):
    match_id: str
    since: int
    next_since: int
    events: list[EventOut]
    status: str


class MatchListItem(BaseModel):
    match_id: str
    status: str
    players: list[PlayerOut]
    current_seat: int | None
    created_at: str
    move_count: int
    # Seconds elapsed since the match was created. Convenient for lobby UI
    # ("waited 12s") and for agents scanning for still-open rooms.
    waited_sec: int
    invite_url: str


class MoveOut(BaseModel):
    """Flat representation of a single placed stone, optimised for replay."""

    seq: int  # event seq (useful for scrubbing)
    move_number: int  # 1..N
    seat: int
    color: Literal["black", "white"]
    x: int
    y: int
    ts: str  # ISO timestamp of the action
    spent_ms: int | None = None  # time since previous move
    comment: str | None = None
    analysis: dict[str, Any] | None = None


class MovesOut(BaseModel):
    match_id: str
    status: str
    total_moves: int
    moves: list[MoveOut]
    result: dict[str, Any] | None = None
    players: list[PlayerOut]
    config: dict[str, Any]
    created_at: str
    finished_at: str | None = None
