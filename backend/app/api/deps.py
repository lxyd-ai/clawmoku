"""
Shared FastAPI dependencies — mostly bearer-key resolution.
"""

from __future__ import annotations

from fastapi import Cookie, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.models.agent import Agent
from app.models.owner import Owner
from app.services import agent_service, auth_service
from app.services.auth_service import JWTError


def _parse_bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip()


async def optional_agent(
    authorization: str | None = Header(default=None),
    session: AsyncSession = Depends(get_db),
) -> Agent | None:
    """Resolve `Authorization: Bearer ...` → Agent, or None if absent.

    Returns None on *missing* header; raises 401 if the header is present but
    malformed or the key is invalid. That way the caller can rely on the "auth
    header was provided" signal.
    """
    raw = _parse_bearer(authorization)
    if raw is None and not authorization:
        return None
    if raw is None:
        raise HTTPException(
            status_code=401,
            detail={"error": "invalid_api_key", "message": "Authorization 头格式必须是 'Bearer <key>'"},
        )
    try:
        return await agent_service.authenticate(session, raw)
    except agent_service.AgentUnauthorized as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": e.code, "message": e.message},
        ) from e


async def require_agent(
    agent: Agent | None = Depends(optional_agent),
) -> Agent:
    if agent is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "auth_required",
                "message": "此接口需要 Authorization: Bearer <api_key>",
            },
        )
    return agent


# ── owner session (cookie-based, set by ClawdChat SSO callback) ──
#
# `optional_owner` is built at module-import time so the cookie name comes
# from settings (one source of truth). Tests that need to override the
# cookie name should monkeypatch `get_settings()` before importing.


def _build_optional_owner():
    cookie_name = get_settings().session_cookie_name

    async def _dep(
        session: AsyncSession = Depends(get_db),
        raw: str | None = Cookie(default=None, alias=cookie_name),
    ) -> Owner | None:
        if not raw:
            return None
        try:
            owner_id = auth_service.read_session_token(raw)
        except JWTError:
            return None
        return await session.get(Owner, owner_id)

    return _dep


optional_owner = _build_optional_owner()


async def require_owner(
    owner: Owner | None = Depends(optional_owner),
) -> Owner:
    if owner is None:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "login_required",
                "message": "需要登录（虾聊账号）才能访问此接口",
            },
        )
    return owner
