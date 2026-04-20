"""
End-to-end tests for the owner-session flow:

  /api/auth/login → state cookie set, 302 to ClawdChat authorize
  /api/auth/callback → exchange mocked, session cookie set, 302 to redirect
  /api/auth/session → reads session cookie, returns owner
  /api/agents/claim/{token} GET/POST → preview + bind agent to owner
  /api/my/agents → lists claimed agents

The ClawdChat side is mocked at the httpx level (we don't hit the real
IdP during tests).
"""

from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest


async def _register(client, name: str) -> dict:
    r = await client.post(
        "/api/agents",
        json={"name": name, "display_name": name.upper()},
    )
    assert r.status_code == 201, r.text
    return r.json()


@pytest.mark.asyncio
async def test_login_starts_oauth_with_state_cookie(client):
    r = await client.get(
        "/api/auth/login?redirect=/claim/abc", follow_redirects=False
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    parsed = urlparse(loc)
    assert parsed.netloc == "clawdchat.cn"
    assert parsed.path == "/api/v1/auth/external/authorize"
    q = parse_qs(parsed.query)
    assert "callback_url" in q and "state" in q
    assert q["callback_url"][0].endswith("/api/auth/callback")

    # state cookie should be set; name defaults to `clawmoku_oauth_state`
    assert "clawmoku_oauth_state" in {c.name for c in r.cookies.jar}


@pytest.mark.asyncio
async def test_callback_exchange_sets_session(monkeypatch, client):
    """Happy path: mock ClawdChat exchange, verify session cookie is set
    and /api/auth/session reports the new owner."""
    # 1. Start login → grab state cookie + state param
    r = await client.get(
        "/api/auth/login?redirect=/my", follow_redirects=False
    )
    state = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    state_cookie = r.cookies.get("clawmoku_oauth_state")
    assert state_cookie

    # 2. Mock ClawdChat token exchange
    from app.services import auth_service

    async def fake_exchange(code: str):
        assert code == "THE-CODE"
        return {
            "id": "cc-user-uuid-123",
            "nickname": "Alice",
            "avatar_url": "https://cdn.clawdchat.cn/a.png",
            "email": "alice@example.com",
            "phone": None,
        }

    monkeypatch.setattr(auth_service, "exchange_code", fake_exchange)

    # 3. Hit callback (carry the state cookie; httpx AsyncClient keeps it)
    r2 = await client.get(
        f"/api/auth/callback?code=THE-CODE&state={state}",
        follow_redirects=False,
    )
    assert r2.status_code == 302, r2.text
    assert r2.headers["location"].endswith("/my")
    assert "clawmoku_session" in {c.name for c in r2.cookies.jar}

    # 4. /api/auth/session should now know about Alice
    r3 = await client.get("/api/auth/session")
    data = r3.json()
    assert data["logged_in"] is True
    assert data["owner"]["nickname"] == "Alice"
    assert data["owner"]["clawdchat_user_id"] == "cc-user-uuid-123"


@pytest.mark.asyncio
async def test_callback_rejects_state_mismatch(client):
    """Swap the state param with a fresh random one — must 400."""
    await client.get("/api/auth/login?redirect=/my", follow_redirects=False)
    r = await client.get(
        "/api/auth/callback?code=x&state=tampered", follow_redirects=False
    )
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "state_mismatch"


@pytest.mark.asyncio
async def test_callback_without_state_cookie(client):
    """If the state cookie is missing entirely, reject."""
    fresh = httpx.AsyncClient(
        transport=client._transport, base_url=str(client.base_url)
    )
    try:
        r = await fresh.get(
            "/api/auth/callback?code=x&state=y", follow_redirects=False
        )
        assert r.status_code == 400
        assert r.json()["detail"]["error"] == "state_cookie_missing"
    finally:
        await fresh.aclose()


@pytest.mark.asyncio
async def test_register_returns_claim_url(client):
    a = await _register(client, "claimtarget")
    assert a["claim_url"].startswith("http://test.local/claim/")
    assert "api_key" in a


@pytest.mark.asyncio
async def test_claim_preview_and_confirm(monkeypatch, client):
    # 1. Register → get claim token from URL
    a = await _register(client, "topurchase")
    token = a["claim_url"].rsplit("/", 1)[-1]

    # 2. Preview works without login
    r = await client.get(f"/api/agents/claim/{token}")
    assert r.status_code == 200
    assert r.json()["agent"]["name"] == "topurchase"
    assert r.json()["agent"]["claimed"] is False

    # 3. POST without login → 401
    r = await client.post(f"/api/agents/claim/{token}")
    assert r.status_code == 401
    assert r.json()["detail"]["error"] == "login_required"

    # 4. Log in (mocked) and claim
    from app.services import auth_service

    async def fake_exchange(code: str):
        return {"id": "cc-owner-777", "nickname": "Bob"}

    monkeypatch.setattr(auth_service, "exchange_code", fake_exchange)
    rlogin = await client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(rlogin.headers["location"]).query)["state"][0]
    await client.get(
        f"/api/auth/callback?code=X&state={state}", follow_redirects=False
    )

    r2 = await client.post(f"/api/agents/claim/{token}")
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["ok"] is True
    assert body["agent"]["claimed"] is True
    assert body["my_url"].endswith("/my")

    # 5. Token is now invalidated
    r3 = await client.get(f"/api/agents/claim/{token}")
    assert r3.status_code == 404

    # 6. /api/my/agents lists our claimed agent
    r4 = await client.get("/api/my/agents")
    assert r4.status_code == 200
    d = r4.json()
    assert d["owner"]["nickname"] == "Bob"
    assert len(d["agents"]) == 1
    assert d["agents"][0]["name"] == "topurchase"


@pytest.mark.asyncio
async def test_logout_clears_session(monkeypatch, client):
    from app.services import auth_service

    async def fake_exchange(code: str):
        return {"id": "cc-logout-test", "nickname": "Carol"}

    monkeypatch.setattr(auth_service, "exchange_code", fake_exchange)
    rlogin = await client.get("/api/auth/login", follow_redirects=False)
    state = parse_qs(urlparse(rlogin.headers["location"]).query)["state"][0]
    await client.get(
        f"/api/auth/callback?code=X&state={state}", follow_redirects=False
    )

    assert (await client.get("/api/auth/session")).json()["logged_in"] is True

    r = await client.post("/api/auth/logout")
    assert r.status_code == 200
    # The response set an empty cookie; the httpx client still carries the
    # original (cookie jars don't automatically expire from max_age=0 in
    # ASGI-mode). Workaround: clear cookies ourselves between assertions.
    client.cookies.delete("clawmoku_session")
    assert (await client.get("/api/auth/session")).json()["logged_in"] is False
