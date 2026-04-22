from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _short_id() -> str:
    return secrets.token_hex(4)  # 8 hex chars


class Match(Base):
    __tablename__ = "matches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_short_id)
    game: Mapped[str] = mapped_column(String(32), default="gomoku", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="waiting", nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    state: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    event_seq: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    players: Mapped[list[MatchPlayer]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MatchPlayer.seat",
    )
    events: Mapped[list[MatchEvent]] = relationship(
        back_populates="match",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="MatchEvent.seq",
    )


class MatchPlayer(Base):
    __tablename__ = "match_players"
    __table_args__ = (UniqueConstraint("match_id", "seat", name="uq_match_player_seat"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    seat: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    play_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional FK to Agent. NULL means "guest" (anonymous legacy flow).
    agent_id: Mapped[str | None] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )
    meta: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    joined_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    # Heartbeat: updated every time this seat's controller calls any
    # observation/action endpoint on the match (GET, /action, /join, /abort,
    # /resign). Powers two things:
    #   1. Lobby "attendance light" — spectators can see at a glance whether
    #      an agent is actively staring at the board (long-polling) or has
    #      walked away.
    #   2. Janitor's idle-host sweep — a `waiting` room whose host hasn't
    #      been seen for N minutes is auto-aborted, keeping the lobby tidy
    #      without waiting for the 30-min hard cap.
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    match: Mapped[Match] = relationship(back_populates="players")


class MatchEvent(Base):
    __tablename__ = "match_events"
    __table_args__ = (UniqueConstraint("match_id", "seq", name="uq_match_event_seq"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )

    match: Mapped[Match] = relationship(back_populates="events")
