from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()

# Ensure ./data directory exists for the default sqlite path.
if _settings.database_url.startswith("sqlite"):
    db_path = _settings.database_url.split("///", 1)[-1]
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    future=True,
    connect_args=(
        {"check_same_thread": False}
        if _settings.database_url.startswith("sqlite")
        else {}
    ),
)

async_session_maker: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine, expire_on_commit=False, class_=AsyncSession
)


async def get_db() -> AsyncIterator[AsyncSession]:
    async with async_session_maker() as session:
        yield session


async def init_db() -> None:
    """Create all tables. For Step 1 we do not use Alembic; plain metadata + a
    handful of idempotent ALTERs is enough for the hand-rolled migrations we've
    needed so far."""
    # Import models so Base.metadata is populated.
    from app.models import agent, match, owner  # noqa: F401

    from sqlalchemy import text

    async with engine.begin() as conn:
        if _settings.database_url.startswith("sqlite"):
            await conn.execute(text("PRAGMA journal_mode=WAL"))
            await conn.execute(text("PRAGMA synchronous=NORMAL"))
        await conn.run_sync(Base.metadata.create_all)

        # ── micro-migrations: columns added after the first release. Each
        #    statement is wrapped in try/except so re-running is a no-op.
        migrations = [
            "ALTER TABLE match_players ADD COLUMN agent_id VARCHAR(32)",
            # owners / claim flow (added when ClawdChat-SSO owner login landed)
            "ALTER TABLE agents ADD COLUMN owner_id VARCHAR(32)",
            "ALTER TABLE agents ADD COLUMN claim_token VARCHAR(64)",
            "ALTER TABLE agents ADD COLUMN claimed_at TIMESTAMP",
            "CREATE INDEX IF NOT EXISTS ix_agents_owner_id ON agents(owner_id)",
            "CREATE UNIQUE INDEX IF NOT EXISTS ix_agents_claim_token ON agents(claim_token)",
            # Per-seat heartbeat for lobby attendance light + idle-host
            # janitor sweep. Backfilled lazily: NULL means "we haven't
            # observed a poll yet" and the janitor treats it as `joined_at`.
            "ALTER TABLE match_players ADD COLUMN last_seen_at TIMESTAMP",
        ]
        for stmt in migrations:
            try:
                await conn.execute(text(stmt))
            except Exception:  # noqa: BLE001 — column already exists etc.
                pass
