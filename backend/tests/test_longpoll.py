from __future__ import annotations

import asyncio
import time

import pytest


@pytest.mark.asyncio
async def test_longpoll_wakes_on_event(client):
    a = (
        await client.post(
            "/api/matches",
            json={"game": "gomoku", "player": {"name": "a"}},
        )
    ).json()
    b = (
        await client.post(
            f"/api/matches/{a['match_id']}/join",
            json={"player": {"name": "b"}},
        )
    ).json()
    mid = a["match_id"]

    # Spectator subscribes from current events_total
    events_total = (await client.get(f"/api/matches/{mid}")).json()["events_total"]

    async def spectator():
        return await client.get(
            f"/api/matches/{mid}/events?since={events_total}&wait=5"
        )

    async def mover():
        # Wait a beat so the long-poll is actually waiting.
        await asyncio.sleep(0.3)
        await client.post(
            f"/api/matches/{mid}/action",
            headers={"X-Play-Token": a["play_token"]},
            json={"type": "place_stone", "x": 7, "y": 7},
        )

    t0 = time.monotonic()
    resp, _ = await asyncio.gather(spectator(), mover())
    dt = time.monotonic() - t0

    assert resp.status_code == 200
    data = resp.json()
    types = [e["type"] for e in data["events"]]
    assert "stone_placed" in types
    assert data["next_since"] > events_total
    assert dt < 4  # should return well before 5s wait cap


@pytest.mark.asyncio
async def test_longpoll_no_duplicate_events(client):
    a = (
        await client.post(
            "/api/matches", json={"game": "gomoku", "player": {"name": "x"}}
        )
    ).json()
    b = (
        await client.post(
            f"/api/matches/{a['match_id']}/join",
            json={"player": {"name": "y"}},
        )
    ).json()
    mid = a["match_id"]

    # a places, b places
    await client.post(
        f"/api/matches/{mid}/action",
        headers={"X-Play-Token": a["play_token"]},
        json={"type": "place_stone", "x": 7, "y": 7},
    )
    await client.post(
        f"/api/matches/{mid}/action",
        headers={"X-Play-Token": b["play_token"]},
        json={"type": "place_stone", "x": 8, "y": 8},
    )

    # Fetch events in two batches and ensure seqs are contiguous and unique
    r1 = (await client.get(f"/api/matches/{mid}/events?since=0&wait=0")).json()
    seqs = [e["seq"] for e in r1["events"]]
    assert seqs == list(range(1, len(seqs) + 1))

    r2 = (
        await client.get(
            f"/api/matches/{mid}/events?since={r1['next_since']}&wait=0"
        )
    ).json()
    assert r2["events"] == []
    assert r2["next_since"] == r1["next_since"]


@pytest.mark.asyncio
async def test_turn_timeout_forfeit(client, monkeypatch):
    # Env fixture sets default turn_timeout=4s; we speed up further via config.
    a = (
        await client.post(
            "/api/matches",
            json={
                "game": "gomoku",
                "config": {"turn_timeout": 2},
                "player": {"name": "slow_a"},
            },
        )
    ).json()
    b = (
        await client.post(
            f"/api/matches/{a['match_id']}/join",
            json={"player": {"name": "slow_b"}},
        )
    ).json()
    mid = a["match_id"]

    # Do nothing for ~3 seconds → black should forfeit.
    await asyncio.sleep(3.0)

    snap = (await client.get(f"/api/matches/{mid}")).json()
    assert snap["status"] == "finished"
    assert snap["result"]["reason"] == "timeout"
    assert snap["result"]["winner_seat"] == 1

    events = (await client.get(f"/api/matches/{mid}/events?since=0&wait=0")).json()
    types = [e["type"] for e in events["events"]]
    assert "turn_warning" in types
    assert "turn_forfeit" in types
    assert "match_finished" in types
