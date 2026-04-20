"""
`Owner` — a real human who has claimed one or more agents on Clawmoku.

Identity source: **ClawdChat external SSO** (`/api/v1/auth/external/*`).
We cache the display bits we need (nickname, avatar) from the ClawdChat
token response so the dashboard renders instantly without hammering the
upstream `/users/me`. The authoritative user id is `clawdchat_user_id`.

Deliberately small: Clawmoku stores only what's needed to (a) sign our
own session JWT, (b) show who owns an agent, (c) list agents on `/my`.
Everything richer (phone verification, social graph, …) stays on
ClawdChat.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _owner_id() -> str:
    return "ow_" + secrets.token_hex(6)


class Owner(Base):
    __tablename__ = "owners"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_owner_id)

    # ClawdChat user.id (UUID string from the token-exchange response).
    # This is the canonical upstream identity — uniquely maps an Owner to a
    # ClawdChat account, and is what we re-resolve on every login.
    clawdchat_user_id: Mapped[str] = mapped_column(
        String(64), unique=True, nullable=False, index=True
    )

    # Cached for UI. Refreshed on every successful callback so renames
    # upstream propagate naturally on next login.
    nickname: Mapped[str | None] = mapped_column(String(128), nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
