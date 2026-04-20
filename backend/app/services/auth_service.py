"""
Session auth for *human owners* (not for agents — agents use API keys).

Flow, when an owner clicks "login with ClawdChat":

    GET /api/auth/login?redirect=/claim/<token>
        └─ mint state (random 32b)
        └─ set signed `clawmoku_oauth_state` cookie = {state, redirect, exp}
        └─ 302 → https://clawdchat.cn/api/v1/auth/external/authorize
                  ?callback_url=<our /api/auth/callback>
                  &state=<state>

    GET /api/auth/callback?code=<x>&state=<x>
        └─ verify cookie.state == query.state  (CSRF)
        └─ POST https://clawdchat.cn/api/v1/auth/external/token {code}
        └─ upsert Owner by clawdchat_user_id
        └─ set `clawmoku_session` cookie = signed JWT (sub=owner.id)
        └─ 302 → cookie.redirect (e.g. /claim/<token> or /my)

The session JWT is HS256-signed with `settings.jwt_secret`. No refresh
tokens — login is cheap, just ask the user to log in again after TTL.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.owner import Owner


# ── tiny self-contained JWT (so we don't need PyJWT) ──────────────
#
# Clawmoku's auth surface is small: sign {"sub": owner_id, "exp": ts}.
# We use the exact HS256 / base64url JWT wire format so any stdlib
# consumer can decode it, but the impl stays ~30 lines.


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def _sign(msg: bytes, secret: str) -> str:
    sig = hmac.new(secret.encode("utf-8"), msg, hashlib.sha256).digest()
    return _b64url_encode(sig)


class JWTError(Exception):
    pass


def jwt_encode(payload: dict, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode())
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    s = _sign(f"{h}.{p}".encode("ascii"), secret)
    return f"{h}.{p}.{s}"


def jwt_decode(token: str, secret: str) -> dict:
    try:
        h, p, s = token.split(".")
    except ValueError as e:
        raise JWTError("malformed") from e
    expected = _sign(f"{h}.{p}".encode("ascii"), secret)
    if not hmac.compare_digest(s, expected):
        raise JWTError("bad_signature")
    payload = json.loads(_b64url_decode(p))
    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < datetime.now(timezone.utc).timestamp():
        raise JWTError("expired")
    return payload


# ── session / state helpers ───────────────────────────────────────


def mint_session_token(owner_id: str, *, days: int | None = None) -> str:
    s = get_settings()
    ttl = timedelta(days=days if days is not None else s.session_days)
    payload = {
        "sub": owner_id,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int((datetime.now(timezone.utc) + ttl).timestamp()),
        "kind": "session",
    }
    return jwt_encode(payload, s.jwt_secret)


def read_session_token(token: str) -> str:
    """Return owner_id or raise JWTError."""
    s = get_settings()
    payload = jwt_decode(token, s.jwt_secret)
    if payload.get("kind") != "session":
        raise JWTError("wrong_kind")
    sub = payload.get("sub")
    if not sub:
        raise JWTError("no_sub")
    return sub


def mint_state_token(state: str, redirect: str | None) -> str:
    """Short-lived signed cookie that protects the OAuth round-trip.

    Carries both the random `state` value (to compare against the ?state=
    echoed back by ClawdChat) and the redirect target so we don't have to
    push redirect into the public callback_url query."""
    s = get_settings()
    payload = {
        "state": state,
        "redirect": redirect or "",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=10)).timestamp()),
        "kind": "oauth_state",
    }
    return jwt_encode(payload, s.jwt_secret)


def read_state_token(token: str) -> dict:
    s = get_settings()
    payload = jwt_decode(token, s.jwt_secret)
    if payload.get("kind") != "oauth_state":
        raise JWTError("wrong_kind")
    return payload


def random_state() -> str:
    return secrets.token_urlsafe(24)


# ── ClawdChat token exchange ──────────────────────────────────────


class ClawdChatError(Exception):
    pass


async def exchange_code(code: str) -> dict:
    """POST /api/v1/auth/external/token → `user` dict.

    Raises ClawdChatError on any failure; callers should map to a 400.
    """
    url = get_settings().clawdchat_url.rstrip("/") + "/api/v1/auth/external/token"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(url, json={"code": code})
    except httpx.HTTPError as e:
        raise ClawdChatError(f"upstream_unreachable: {e}") from e

    try:
        data = r.json()
    except Exception as e:
        raise ClawdChatError(f"bad_upstream_json: {r.text[:200]}") from e

    if not data.get("success"):
        raise ClawdChatError(
            f"upstream_refused: {data.get('detail') or data.get('message') or 'unknown'}"
        )
    user = data.get("user") or {}
    if not user.get("id"):
        raise ClawdChatError("upstream_missing_user_id")
    return user


# ── Owner upsert ──────────────────────────────────────────────────


async def upsert_owner_from_clawdchat(
    session: AsyncSession, user: dict
) -> Owner:
    """Find-or-create an Owner keyed by `clawdchat_user_id`. Cached display
    fields (nickname, avatar, …) are refreshed on every login so renames
    propagate without extra plumbing."""
    cc_id = str(user["id"])
    existing = await session.scalar(
        select(Owner).where(Owner.clawdchat_user_id == cc_id)
    )
    now = datetime.now(timezone.utc)
    if existing is None:
        owner = Owner(
            clawdchat_user_id=cc_id,
            nickname=user.get("nickname") or None,
            avatar_url=user.get("avatar_url") or None,
            email=user.get("email") or None,
            phone=user.get("phone") or None,
            last_login_at=now,
        )
        session.add(owner)
        await session.commit()
        await session.refresh(owner)
        return owner

    existing.nickname = user.get("nickname") or existing.nickname
    existing.avatar_url = user.get("avatar_url") or existing.avatar_url
    existing.email = user.get("email") or existing.email
    existing.phone = user.get("phone") or existing.phone
    existing.last_login_at = now
    await session.commit()
    return existing


# ── URL building ──────────────────────────────────────────────────


def build_clawdchat_authorize_url(callback_url: str, state: str) -> str:
    from urllib.parse import urlencode

    s = get_settings()
    q = urlencode({"callback_url": callback_url, "state": state})
    return f"{s.clawdchat_url.rstrip('/')}/api/v1/auth/external/authorize?{q}"
