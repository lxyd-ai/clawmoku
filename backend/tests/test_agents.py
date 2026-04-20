from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_register_and_profile(client):
    r = await client.post(
        "/api/agents",
        json={"name": "alice-gpt", "display_name": "Alice", "bio": "hi"},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "alice-gpt"
    assert body["api_key"].startswith("ck_live_")
    assert body["api_key_prefix"] == body["api_key"][:12]
    assert body["wins"] == 0 and body["losses"] == 0 and body["draws"] == 0
    assert body["profile_url"].endswith("/agents/alice-gpt")

    # public profile does NOT leak the api_key
    r2 = await client.get("/api/agents/alice-gpt")
    assert r2.status_code == 200
    p = r2.json()
    assert "api_key" not in p
    assert p["display_name"] == "Alice"

    # me endpoint needs auth
    r3 = await client.get("/api/agents/me")
    assert r3.status_code == 401

    r4 = await client.get(
        "/api/agents/me",
        headers={"Authorization": f"Bearer {body['api_key']}"},
    )
    assert r4.status_code == 200
    me = r4.json()
    assert me["name"] == "alice-gpt"
    assert me["api_key_prefix"] == body["api_key_prefix"]
    assert "api_key" not in me


@pytest.mark.asyncio
async def test_register_name_rules(client):
    bad = [
        {"name": "Ab"},
        {"name": "with space"},
        {"name": "-dash"},
        {"name": "a" * 70},  # >64 chars (spec §3.3 / R1 upper bound)
        {"name": "1abc"},  # must start with letter
    ]
    for payload in bad:
        r = await client.post("/api/agents", json=payload)
        assert r.status_code in (400, 422), f"{payload} -> {r.status_code}"

    r = await client.post("/api/agents", json={"name": "bob"})
    assert r.status_code == 201
    # duplicate
    r2 = await client.post("/api/agents", json={"name": "bob"})
    assert r2.status_code == 409
    assert r2.json()["detail"]["error"] == "name_taken"


@pytest.mark.asyncio
async def test_rotate_key_invalidates_old(client):
    r = await client.post("/api/agents", json={"name": "carol"})
    old = r.json()["api_key"]
    r2 = await client.post(
        "/api/agents/me/rotate-key",
        headers={"Authorization": f"Bearer {old}"},
    )
    assert r2.status_code == 200
    new = r2.json()["api_key"]
    assert new != old
    # old key no longer works
    r3 = await client.get(
        "/api/agents/me", headers={"Authorization": f"Bearer {old}"}
    )
    assert r3.status_code == 401
    # new key works
    r4 = await client.get(
        "/api/agents/me", headers={"Authorization": f"Bearer {new}"}
    )
    assert r4.status_code == 200


@pytest.mark.asyncio
async def test_bearer_match_flow_and_stats(client):
    # register two agents
    a_reg = (
        await client.post(
            "/api/agents",
            json={"name": "player-a", "display_name": "Player A"},
        )
    ).json()
    b_reg = (
        await client.post(
            "/api/agents",
            json={"name": "player-b", "display_name": "Player B"},
        )
    ).json()
    a_key = a_reg["api_key"]
    b_key = b_reg["api_key"]
    auth_a = {"Authorization": f"Bearer {a_key}"}
    auth_b = {"Authorization": f"Bearer {b_key}"}

    # create with key — no player body needed
    r = await client.post(
        "/api/matches",
        json={"game": "gomoku"},
        headers=auth_a,
    )
    assert r.status_code == 201, r.text
    match_id = r.json()["match_id"]

    # second agent joins with their key
    r = await client.post(
        f"/api/matches/{match_id}/join", json={}, headers=auth_b
    )
    assert r.status_code == 200, r.text

    # snapshot shows both players with agent_id set, is_guest False
    snap = (await client.get(f"/api/matches/{match_id}")).json()
    assert snap["status"] == "in_progress"
    assert all(not p["is_guest"] for p in snap["players"])
    assert {p["name"] for p in snap["players"]} == {"player-a", "player-b"}

    # wrong key can't submit action
    r = await client.post(
        f"/api/matches/{match_id}/action",
        json={"type": "place_stone", "x": 0, "y": 0},
        headers={"Authorization": "Bearer ck_live_notreal"},
    )
    assert r.status_code == 401

    # player-a (seat 0, black) moves first down the main diagonal;
    # player-b must block to avoid losing.
    moves_a = [(7, 7), (8, 8), (9, 9), (10, 10), (11, 11)]
    moves_b = [(0, 0), (0, 1), (0, 2), (0, 3)]
    for i in range(5):
        r = await client.post(
            f"/api/matches/{match_id}/action",
            json={"type": "place_stone", "x": moves_a[i][0], "y": moves_a[i][1]},
            headers=auth_a,
        )
        assert r.status_code == 200, r.text
        if r.json().get("status") == "finished":
            break
        # b moves unless the game already ended
        bi = i
        if bi < len(moves_b):
            r = await client.post(
                f"/api/matches/{match_id}/action",
                json={"type": "place_stone", "x": moves_b[bi][0], "y": moves_b[bi][1]},
                headers=auth_b,
            )
            assert r.status_code == 200, r.text
            if r.json().get("status") == "finished":
                break

    snap = (await client.get(f"/api/matches/{match_id}")).json()
    assert snap["status"] == "finished"
    assert snap["result"]["winner_seat"] == 0

    # stats should have updated
    a = (await client.get("/api/agents/player-a")).json()
    b = (await client.get("/api/agents/player-b")).json()
    assert a["wins"] == 1 and a["losses"] == 0
    assert b["wins"] == 0 and b["losses"] == 1


@pytest.mark.asyncio
async def test_guest_mode_still_works(client):
    r = await client.post(
        "/api/matches",
        json={"game": "gomoku", "player": {"name": "guest-x"}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["play_token"].startswith("pk_")
    match_id = body["match_id"]

    snap = (await client.get(f"/api/matches/{match_id}")).json()
    assert snap["players"][0]["is_guest"] is True
    assert snap["players"][0]["agent_id"] is None


@pytest.mark.asyncio
async def test_agent_cannot_double_sit(client):
    reg = (
        await client.post("/api/agents", json={"name": "solo-agent"})
    ).json()
    auth = {"Authorization": f"Bearer {reg['api_key']}"}

    r = await client.post("/api/matches", json={"game": "gomoku"}, headers=auth)
    match_id = r.json()["match_id"]

    r2 = await client.post(
        f"/api/matches/{match_id}/join", json={}, headers=auth
    )
    assert r2.status_code == 409
    assert r2.json()["detail"]["error"] in {"duplicate_agent", "duplicate_player"}
