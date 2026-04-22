"""
Tests for the one-board-per-agent rule, the /me/active self-check endpoint,
the per-seat `last_seen_at` heartbeat surface, and the janitor's new idle-host
sweep.

These all share a common design goal: make it safe for an agent to forget it
already has a room open, and make it visible to lobby spectators whether the
agents at the table are actually paying attention.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest


async def _register(client, name):
    r = await client.post("/api/agents", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def _auth(reg):
    return {"Authorization": f"Bearer {reg['api_key']}"}


@pytest.mark.asyncio
async def test_me_active_null_when_no_match(client):
    a = await _register(client, "solo1")
    r = await client.get("/api/agents/me/active", headers=_auth(a))
    assert r.status_code == 200
    assert r.json() == {"active": None}


@pytest.mark.asyncio
async def test_me_active_reports_waiting_match(client):
    a = await _register(client, "solo2")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    match_id = r.json()["match_id"]

    r = await client.get("/api/agents/me/active", headers=_auth(a))
    body = r.json()
    assert body["active"] is not None
    assert body["active"]["match_id"] == match_id
    assert body["active"]["status"] == "waiting"
    assert body["active"]["seat"] == 0
    assert body["active"]["invite_url"].endswith(f"/match/{match_id}")
    assert body["active"]["opponent"] is None


@pytest.mark.asyncio
async def test_me_active_reports_in_progress_with_opponent(client):
    a = await _register(client, "ap1")
    b = await _register(client, "bp1")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r.json()["match_id"]
    await client.post(
        f"/api/matches/{mid}/join", json={}, headers=_auth(b)
    )

    # seat 0 perspective
    r = await client.get("/api/agents/me/active", headers=_auth(a))
    active = r.json()["active"]
    assert active["status"] == "in_progress"
    assert active["seat"] == 0
    assert active["your_turn"] is True
    assert active["opponent"]["name"] == "bp1"

    # seat 1 perspective
    r = await client.get("/api/agents/me/active", headers=_auth(b))
    active = r.json()["active"]
    assert active["seat"] == 1
    assert active["your_turn"] is False
    assert active["opponent"]["name"] == "ap1"


@pytest.mark.asyncio
async def test_me_active_clears_when_match_finishes(client):
    a = await _register(client, "ap2")
    b = await _register(client, "bp2")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r.json()["match_id"]
    await client.post(f"/api/matches/{mid}/join", json={}, headers=_auth(b))

    # seat 0 resigns → match finished
    r = await client.post(f"/api/matches/{mid}/resign", headers=_auth(a))
    assert r.status_code == 200

    r = await client.get("/api/agents/me/active", headers=_auth(a))
    assert r.json()["active"] is None
    r = await client.get("/api/agents/me/active", headers=_auth(b))
    assert r.json()["active"] is None


@pytest.mark.asyncio
async def test_create_match_refuses_second_concurrent_room(client):
    a = await _register(client, "dup1")
    r1 = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid1 = r1.json()["match_id"]

    r2 = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    assert r2.status_code == 409
    body = r2.json()["detail"]
    assert body["error"] == "already_in_match"
    assert body["match_id"] == mid1
    assert body["invite_url"].endswith(f"/match/{mid1}")
    assert body["status"] == "waiting"


@pytest.mark.asyncio
async def test_join_match_refuses_when_already_in_another(client):
    a = await _register(client, "dup2a")
    b = await _register(client, "dup2b")
    # a opens room 1
    r1 = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid1 = r1.json()["match_id"]
    # b opens room 2
    r2 = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(b))
    mid2 = r2.json()["match_id"]

    # a now tries to join b's room → 409 (a is still in their own room)
    r = await client.post(
        f"/api/matches/{mid2}/join", json={}, headers=_auth(a)
    )
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["error"] == "already_in_match"
    assert body["match_id"] == mid1


@pytest.mark.asyncio
async def test_rejoin_own_room_still_yields_duplicate_agent(client):
    """Calling /join on the room you already opened should keep returning the
    existing `duplicate_agent` conflict rather than the new
    `already_in_match` one — semantically you're a dup, not a two-timer."""
    a = await _register(client, "dup3")
    r1 = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r1.json()["match_id"]
    r2 = await client.post(f"/api/matches/{mid}/join", json={}, headers=_auth(a))
    assert r2.status_code == 409
    assert r2.json()["detail"]["error"] in {"duplicate_agent", "duplicate_player"}


@pytest.mark.asyncio
async def test_can_open_new_match_after_aborting(client):
    a = await _register(client, "reopen1")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r.json()["match_id"]
    await client.post(f"/api/matches/{mid}/abort", headers=_auth(a))

    r2 = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    assert r2.status_code == 201


@pytest.mark.asyncio
async def test_last_seen_at_populated_on_create_and_poll(client):
    a = await _register(client, "hb1")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r.json()["match_id"]

    # Snapshot right after create — host should already have last_seen_at.
    snap = (await client.get(f"/api/matches/{mid}")).json()
    host = next(p for p in snap["players"] if p["seat"] == 0)
    first_ts = host["last_seen_at"]
    assert first_ts is not None

    # Poll again with the agent's identity; heartbeat should advance.
    import asyncio as _a

    await _a.sleep(1.1)
    await client.get(
        f"/api/matches/{mid}?seat=0", headers=_auth(a)
    )
    snap2 = (await client.get(f"/api/matches/{mid}")).json()
    host2 = next(p for p in snap2["players"] if p["seat"] == 0)
    assert host2["last_seen_at"] is not None
    assert host2["last_seen_at"] >= first_ts  # monotonic


@pytest.mark.asyncio
async def test_last_seen_at_bumped_by_action(client):
    a = await _register(client, "hb2a")
    b = await _register(client, "hb2b")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r.json()["match_id"]
    await client.post(f"/api/matches/{mid}/join", json={}, headers=_auth(b))

    snap_before = (await client.get(f"/api/matches/{mid}")).json()
    host_before = next(p for p in snap_before["players"] if p["seat"] == 0)

    import asyncio as _a

    await _a.sleep(1.1)
    # seat 0 plays
    r = await client.post(
        f"/api/matches/{mid}/action",
        json={"type": "place_stone", "x": 7, "y": 7},
        headers=_auth(a),
    )
    assert r.status_code == 200

    snap_after = (await client.get(f"/api/matches/{mid}")).json()
    host_after = next(p for p in snap_after["players"] if p["seat"] == 0)
    assert host_after["last_seen_at"] > host_before["last_seen_at"]


@pytest.mark.asyncio
async def test_janitor_sweeps_idle_host(client, monkeypatch):
    """If seat-0's heartbeat ages past `waiting_host_idle_minutes`, the
    janitor sweep should abort the waiting room even though the hard cap
    hasn't been reached."""
    a = await _register(client, "idle1")
    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=_auth(a))
    mid = r.json()["match_id"]

    # Force the host's last_seen_at far into the past.
    from sqlalchemy import select

    from app.core.db import async_session_maker
    from app.models.match import MatchPlayer

    old = datetime.now(timezone.utc) - timedelta(minutes=15)
    async with async_session_maker() as session:
        player = await session.scalar(
            select(MatchPlayer).where(
                MatchPlayer.match_id == mid, MatchPlayer.seat == 0
            )
        )
        player.last_seen_at = old
        player.joined_at = old
        await session.commit()

    # Shrink idle cap so the sweep triggers on our 15-min-old heartbeat.
    from app.core.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "waiting_host_idle_minutes", 1)
    monkeypatch.setattr(settings, "waiting_max_minutes", 999)  # only idle path fires

    from app.services import janitor

    swept = await janitor._sweep_once()
    assert swept >= 1

    snap = (await client.get(f"/api/matches/{mid}")).json()
    assert snap["status"] == "aborted"
    assert snap["result"]["aborted_by"] == "janitor"
