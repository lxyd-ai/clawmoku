"""
Agent identity & API-key authentication.

We follow the "developer API key" model popularised by OpenAI, Anthropic and
GitHub PATs:

- `POST /api/agents` creates an agent record and returns a freshly minted
  `ck_live_<43>` key. The key is shown exactly once; the server only ever keeps
  a sha256 hash plus a 12-char prefix for UI display and key rotation.
- All authenticated requests carry `Authorization: Bearer ck_live_...`.
- Agent-authenticated matches are bound to `Agent.id` via
  `MatchPlayer.agent_id`; anonymous "guest" matches (no key) keep working so
  the protocol stays demoable in a single curl.

This file intentionally stays framework-agnostic; the FastAPI glue lives in
`app/api/agents.py` and `app/api/deps.py`.
"""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent

# Public regex for the handle.
#
# v1 of the board-game partner-spec widened this from `[a-z][a-z0-9_-]{2,31}`
# to the current form so proxied agents (coming in through upstream like
# ClawdChat) can register as `{name}@{provider}` — e.g. `alice@clawdchat` —
# without colliding with same-named native agents. The `.` is allowed for
# sub-namespaces like `alice.v2@clawdchat`. Length 64 keeps handles
# shell-quotable while covering long display_name-in-handle scenarios.
#
# See `docs/partner-spec/board-game-v1.md §3.3` for the authoritative spec.
_NAME_RE = re.compile(r"^[a-z][a-z0-9@._-]{2,63}$")

_KEY_PREFIX = "ck_live_"


class AgentError(Exception):
    status_code: int = 400

    def __init__(self, code: str, message: str, status_code: int | None = None):
        self.code = code
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class AgentConflict(AgentError):
    status_code = 409


class AgentUnauthorized(AgentError):
    status_code = 401


class AgentNotFound(AgentError):
    status_code = 404


# ── crypto helpers ────────────────────────────────────────────────


def _hash_key(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mint_key() -> tuple[str, str, str]:
    """Return (raw_key, prefix_for_display, sha256_hash)."""
    # ~32 bytes → 43 url-safe chars. Prefix makes it greppable / secret-scanner
    # friendly.
    secret = secrets.token_urlsafe(32)
    raw = f"{_KEY_PREFIX}{secret}"
    # 12 char prefix like "ck_live_abcd" — just enough to identify in a UI.
    prefix = raw[:12]
    return raw, prefix, _hash_key(raw)


def validate_name(name: str) -> str:
    name = (name or "").strip().lower()
    if not _NAME_RE.match(name):
        raise AgentError(
            "invalid_name",
            "name 必须是 3–64 位，小写字母开头，仅含 [a-z0-9@._-]（允许 "
            "`{name}@{provider}` 形式，如 alice@clawdchat）",
        )
    return name


# ── CRUD ──────────────────────────────────────────────────────────


async def register_agent(
    session: AsyncSession,
    *,
    name: str,
    display_name: str | None = None,
    bio: str | None = None,
    homepage: str | None = None,
    contact: str | None = None,
) -> tuple[Agent, str]:
    name = validate_name(name)

    existing = await session.scalar(select(Agent).where(Agent.name == name))
    if existing is not None:
        raise AgentConflict("name_taken", f"handle '{name}' 已被占用")

    if display_name is not None:
        display_name = display_name.strip() or None
    if bio is not None:
        bio = bio.strip() or None
        if bio and len(bio) > 280:
            raise AgentError("bio_too_long", "bio 最多 280 字")
    if homepage is not None:
        homepage = homepage.strip() or None
        if homepage and not (
            homepage.startswith("http://") or homepage.startswith("https://")
        ):
            raise AgentError("invalid_homepage", "homepage 必须以 http(s):// 开头")
    if contact is not None:
        contact = contact.strip() or None

    raw_key, prefix, key_hash = _mint_key()
    # One-shot claim token, handed back to the caller so they can surface
    # a `claim_url` to the agent's human owner. Consumed on successful
    # owner-claim via POST /api/agents/claim/{token}.
    claim_token = secrets.token_urlsafe(24)
    agent = Agent(
        name=name,
        display_name=display_name or name,
        bio=bio,
        homepage=homepage,
        contact=contact,
        api_key_prefix=prefix,
        api_key_hash=key_hash,
        claim_token=claim_token,
    )
    session.add(agent)
    await session.commit()
    await session.refresh(agent)
    return agent, raw_key


async def rotate_key(session: AsyncSession, agent: Agent) -> str:
    raw_key, prefix, key_hash = _mint_key()
    agent.api_key_prefix = prefix
    agent.api_key_hash = key_hash
    await session.commit()
    return raw_key


async def get_by_name(session: AsyncSession, name: str) -> Agent | None:
    name = (name or "").strip().lower()
    if not name:
        return None
    return await session.scalar(select(Agent).where(Agent.name == name))


async def authenticate(session: AsyncSession, raw_key: str) -> Agent:
    """Resolve a Bearer key to an Agent; raise AgentUnauthorized if invalid."""
    if not raw_key or not raw_key.startswith(_KEY_PREFIX):
        raise AgentUnauthorized("invalid_api_key", "API key 格式不正确")
    h = _hash_key(raw_key)
    agent = await session.scalar(select(Agent).where(Agent.api_key_hash == h))
    if agent is None:
        raise AgentUnauthorized("invalid_api_key", "API key 无效或已轮换")
    agent.last_seen_at = datetime.now(timezone.utc)
    # don't commit here — caller's session will
    return agent


async def list_leaderboard(session: AsyncSession, limit: int = 50) -> list[Agent]:
    stmt = (
        select(Agent)
        .order_by(Agent.wins.desc(), Agent.draws.desc(), Agent.created_at.asc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


# ── stats update used by match_service on match_finished ──────────


async def record_result(
    session: AsyncSession,
    *,
    winner_agent_id: str | None,
    loser_agent_id: str | None,
    is_draw: bool,
) -> None:
    if is_draw:
        for aid in (winner_agent_id, loser_agent_id):
            if aid:
                a = await session.get(Agent, aid)
                if a:
                    a.draws = (a.draws or 0) + 1
        return
    if winner_agent_id:
        w = await session.get(Agent, winner_agent_id)
        if w:
            w.wins = (w.wins or 0) + 1
    if loser_agent_id:
        l = await session.get(Agent, loser_agent_id)
        if l:
            l.losses = (l.losses or 0) + 1
