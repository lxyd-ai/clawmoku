"""
Owner-session auth endpoints — `/api/auth/*`.

- `GET  /api/auth/login`      start ClawdChat SSO (302 → upstream)
- `GET  /api/auth/callback`   ClawdChat → us, exchange code, set cookie
- `POST /api/auth/logout`     clear cookie
- `GET  /api/auth/session`    {owner: ..., logged_in: bool} for the UI

Agent-key probe (`/api/auth/check`) lives in `agents.py` — different
kind of identity, same URL family.
"""

from __future__ import annotations

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import optional_owner
from app.core.config import get_settings
from app.core.db import get_db
from app.models.owner import Owner
from app.services import auth_service
from app.services.auth_service import ClawdChatError, JWTError

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _safe_redirect(target: str | None) -> str:
    """Only allow redirects back to our own app. Anything fishy → /my."""
    if not target:
        return "/my"
    if not target.startswith("/") or target.startswith("//"):
        return "/my"
    return target


def _set_state_cookie(response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.oauth_state_cookie_name,
        value=token,
        max_age=600,  # 10 minutes
        httponly=True,
        secure=s.session_cookie_secure,
        samesite=s.session_cookie_samesite,
        path="/",
    )


def _clear_state_cookie(response) -> None:
    s = get_settings()
    response.delete_cookie(
        key=s.oauth_state_cookie_name,
        path="/",
    )


def _set_session_cookie(response, token: str) -> None:
    s = get_settings()
    response.set_cookie(
        key=s.session_cookie_name,
        value=token,
        max_age=s.session_days * 86400,
        httponly=True,
        secure=s.session_cookie_secure,
        samesite=s.session_cookie_samesite,
        path="/",
    )


def _clear_session_cookie(response) -> None:
    s = get_settings()
    response.delete_cookie(
        key=s.session_cookie_name,
        path="/",
    )


def _owner_payload(owner: Owner) -> dict:
    return {
        "owner_id": owner.id,
        "clawdchat_user_id": owner.clawdchat_user_id,
        "nickname": owner.nickname,
        "avatar_url": owner.avatar_url,
        "email": owner.email,
    }


@router.get("/login")
async def login(request: Request, redirect: str = "/my"):
    """Start the ClawdChat SSO round-trip.

    `redirect` is where we'll send the browser **after** login completes.
    It's kept in a signed cookie so the third-party callback URL stays
    nice and short and our redirect target isn't exposed to ClawdChat.
    """
    s = get_settings()
    state = auth_service.random_state()
    redirect_target = _safe_redirect(redirect)
    state_token = auth_service.mint_state_token(state, redirect_target)

    callback_url = s.public_base_url.rstrip("/") + "/api/auth/callback"
    authorize_url = auth_service.build_clawdchat_authorize_url(
        callback_url=callback_url, state=state
    )

    resp = RedirectResponse(url=authorize_url, status_code=302)
    _set_state_cookie(resp, state_token)
    return resp


@router.get("/callback")
async def callback(
    code: str,
    state: str,
    session: AsyncSession = Depends(get_db),
    state_cookie: str | None = Cookie(
        default=None, alias=get_settings().oauth_state_cookie_name
    ),
):
    """ClawdChat → us.

    Verify state, exchange code, upsert owner, set session cookie, 302 to
    the saved redirect target.
    """
    s = get_settings()

    # 1. Validate the state cookie (CSRF + tie to our redirect target)
    if not state_cookie:
        raise HTTPException(400, {"error": "state_cookie_missing"})
    try:
        state_payload = auth_service.read_state_token(state_cookie)
    except JWTError as e:
        raise HTTPException(400, {"error": "state_invalid", "reason": str(e)}) from e
    if state_payload.get("state") != state:
        raise HTTPException(400, {"error": "state_mismatch"})

    # 2. Exchange code for user info
    try:
        user = await auth_service.exchange_code(code)
    except ClawdChatError as e:
        raise HTTPException(400, {"error": "upstream_exchange_failed", "reason": str(e)}) from e

    # 3. Upsert owner
    owner = await auth_service.upsert_owner_from_clawdchat(session, user)

    # 4. Set session cookie + redirect
    session_token = auth_service.mint_session_token(owner.id)
    redirect_target = _safe_redirect(state_payload.get("redirect"))
    full_redirect = s.public_base_url.rstrip("/") + redirect_target

    resp = RedirectResponse(url=full_redirect, status_code=302)
    _set_session_cookie(resp, session_token)
    _clear_state_cookie(resp)
    return resp


@router.post("/logout")
async def logout():
    resp = JSONResponse({"ok": True})
    _clear_session_cookie(resp)
    return resp


@router.get("/session")
async def session_info(owner: Owner | None = Depends(optional_owner)):
    if owner is None:
        return {"logged_in": False, "owner": None}
    return {"logged_in": True, "owner": _owner_payload(owner)}
