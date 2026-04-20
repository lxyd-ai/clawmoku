"""
Owner-claim endpoints for agents.

Flow:
  1. Agent registers → server mints `claim_token` → returns
     `claim_url = {public}/claim/{token}` in the response.
  2. Agent hands the URL to its human owner.
  3. Owner opens the URL in a browser → hits the Next.js `/claim/[token]`
     page → if not logged in, redirects through `/api/auth/login?redirect=/claim/<t>`.
  4. Logged-in page fetches `GET /api/agents/claim/{token}` to show *which*
     agent they're about to claim (preview + confirm).
  5. Clicking "confirm claim" → `POST /api/agents/claim/{token}` binds the
     agent to the owner and invalidates the token.

Naming: we mount at `/api/agents/claim/{token}` (plural `agents`) so the
route sits next to the rest of the agent surface. The *public* claim URL
is `/claim/{token}` (UI page) — backend and front are symmetric.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner
from app.core.config import get_settings
from app.core.db import get_db
from app.models.agent import Agent
from app.models.owner import Owner

router = APIRouter(prefix="/api/agents/claim", tags=["claim"])

# Domains we'll honour as `?return_to=` targets after a successful claim.
# Partner-spec v1 §1.5.1 requires an allowlist to prevent open-redirect.
# Upstream proxies that want their domain added should PR this list; the
# field can later move to a config file without changing the spec.
_RETURN_TO_ALLOWLIST = {
    "clawdchat.cn",
    "www.clawdchat.cn",
    "gomoku.clawd.xin",  # self
    "localhost",
    "127.0.0.1",
}


def _safe_return_to(return_to: str | None) -> str | None:
    """Accept only http(s) URLs whose host is in the allowlist.
    
    Returns the URL as-is when safe, `None` otherwise. Callers should
    fall back to their own `/my` page when this returns `None`.
    """
    if not return_to:
        return None
    try:
        parsed = urlparse(return_to)
    except Exception:  # noqa: BLE001
        return None
    if parsed.scheme not in ("http", "https"):
        return None
    host = (parsed.hostname or "").lower()
    if host not in _RETURN_TO_ALLOWLIST:
        return None
    return return_to


def _public_preview(a: Agent, base: str) -> dict:
    return {
        "agent_id": a.id,
        "name": a.name,
        "display_name": a.display_name,
        "bio": a.bio,
        "wins": a.wins or 0,
        "losses": a.losses or 0,
        "draws": a.draws or 0,
        "profile_url": f"{base}/agents/{a.name}",
        "claimed": a.owner_id is not None,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    }


@router.get("/{token}")
async def preview(
    token: str,
    return_to: str | None = Query(
        default=None,
        description="Optional upstream URL to redirect to after a successful "
        "claim. Must be in the server-side allowlist (partner-spec §1.5.1); "
        "non-allowed values are silently ignored.",
    ),
    session: AsyncSession = Depends(get_db),
):
    """Look up the agent behind a claim token. Safe to call unauthenticated
    — returns a tiny public preview so the claim page can show "you're
    about to claim @alice-gpt" before asking the user to log in."""
    agent = await session.scalar(select(Agent).where(Agent.claim_token == token))
    if agent is None:
        raise HTTPException(
            404,
            {"error": "claim_token_invalid", "message": "认领链接无效或已被使用"},
        )
    base = get_settings().public_base_url.rstrip("/")
    return {
        "agent": _public_preview(agent, base),
        # Echo back the validated return_to so the front-end knows where to
        # send the browser after confirmation. `null` → default to /my.
        "return_to": _safe_return_to(return_to),
    }


@router.post("/{token}")
async def confirm(
    token: str,
    return_to: str | None = Query(
        default=None,
        description="Optional upstream URL to redirect to after a successful "
        "claim (allowlisted, see GET).",
    ),
    owner: Owner = Depends(require_owner),
    session: AsyncSession = Depends(get_db),
):
    """Bind the agent behind `token` to the currently logged-in owner.

    Idempotent-ish: a one-shot token. If the same owner re-submits after a
    successful claim, the token is already gone → 404. Two different
    owners racing the same token → whichever commits first wins; loser
    gets 404. Acceptable.
    """
    agent = await session.scalar(select(Agent).where(Agent.claim_token == token))
    if agent is None:
        raise HTTPException(
            404,
            {"error": "claim_token_invalid", "message": "认领链接无效或已被使用"},
        )
    if agent.owner_id and agent.owner_id != owner.id:
        # Shouldn't happen (token is unique + nulled on claim) but be loud
        raise HTTPException(
            409,
            {
                "error": "already_claimed",
                "message": "这个 agent 已经被另一个主人认领了",
            },
        )

    agent.owner_id = owner.id
    agent.claim_token = None
    agent.claimed_at = datetime.now(timezone.utc)
    await session.commit()
    await session.refresh(agent)

    base = get_settings().public_base_url.rstrip("/")
    safe_return = _safe_return_to(return_to)
    return {
        "ok": True,
        "agent": _public_preview(agent, base),
        "my_url": f"{base}/my",
        # If `return_to` was allowlisted, the claim page should bounce the
        # browser here instead of `my_url`. Null → default behaviour.
        "return_to": safe_return,
    }
