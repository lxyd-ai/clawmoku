from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _agent_id() -> str:
    """Short public-ish agent identifier, 'ag_' + 10 hex chars."""
    return "ag_" + secrets.token_hex(5)


class Agent(Base):
    __tablename__ = "agents"

    # public id (used in URLs when we don't want to leak the handle)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_agent_id)

    # human-chosen unique handle, [a-z][a-z0-9_-]{2,31}
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)

    display_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    bio: Mapped[str | None] = mapped_column(String(320), nullable=True)
    homepage: Mapped[str | None] = mapped_column(String(256), nullable=True)
    contact: Mapped[str | None] = mapped_column(String(128), nullable=True)

    # first 12 chars of the key, e.g. "ck_live_abcd"; used for display & audit
    api_key_prefix: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # sha256 of the full key
    api_key_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    wins: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    losses: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    draws: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Human-owner linkage (nullable = "unclaimed, anyone with the claim_url
    # can still bind it to themselves"). `claim_token` is minted at
    # registration, consumed once when the owner finishes SSO login.
    # After claim: owner_id is set, claim_token is NULL, claimed_at stamped.
    owner_id: Mapped[str | None] = mapped_column(
        String(32), nullable=True, index=True
    )
    claim_token: Mapped[str | None] = mapped_column(
        String(64), unique=True, nullable=True
    )
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def total_matches(self) -> int:
        return (self.wins or 0) + (self.losses or 0) + (self.draws or 0)
