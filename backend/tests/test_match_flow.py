from __future__ import annotations

import pytest


async def _create(client, name):
    r = await client.post(
        "/api/matches",
        json={"game": "gomoku", "player": {"name": name, "display_name": name}},
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _join(client, match_id, name):
    r = await client.post(
        f"/api/matches/{match_id}/join",
        json={"player": {"name": name}},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _move(client, match_id, token, x, y, *, expect=200):
    r = await client.post(
        f"/api/matches/{match_id}/action",
        headers={"X-Play-Token": token},
        json={"type": "place_stone", "x": x, "y": y},
    )
    assert r.status_code == expect, r.text
    return r.json()


@pytest.mark.asyncio
async def test_full_two_agent_game(client):
    a = await _create(client, "alice")
    assert a["seat"] == 0 and a["status"] == "waiting"
    b = await _join(client, a["match_id"], "bob")
    assert b["seat"] == 1 and b["status"] == "in_progress"

    token_a, token_b = a["play_token"], b["play_token"]
    mid = a["match_id"]

    # black plays five in a row at y=7; white plays filler elsewhere
    black_moves = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    white_moves = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4)]

    last = None
    for i, bm in enumerate(black_moves):
        resp = await _move(client, mid, token_a, *bm)
        last = resp
        if resp.get("status") == "finished":
            break
        await _move(client, mid, token_b, *white_moves[i])

    assert last["status"] == "finished"
    assert last["result"]["winner_seat"] == 0
    assert "replay_url" in last["result"]

    # Snapshot reflects finish
    snap = (await client.get(f"/api/matches/{mid}")).json()
    assert snap["status"] == "finished"
    assert snap["result"]["winner_seat"] == 0
    assert snap["current_seat"] is None


@pytest.mark.asyncio
async def test_not_your_turn_and_token_checks(client):
    a = await _create(client, "a1")
    b = await _join(client, a["match_id"], "b1")
    mid = a["match_id"]

    # white tries first — should 409 not_your_turn
    r = await client.post(
        f"/api/matches/{mid}/action",
        headers={"X-Play-Token": b["play_token"]},
        json={"type": "place_stone", "x": 7, "y": 7},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "not_your_turn"

    # bad token
    r = await client.post(
        f"/api/matches/{mid}/action",
        headers={"X-Play-Token": "pk_nonsense"},
        json={"type": "place_stone", "x": 7, "y": 7},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_join_full(client):
    a = await _create(client, "x")
    await _join(client, a["match_id"], "y")
    r = await client.post(
        f"/api/matches/{a['match_id']}/join",
        json={"player": {"name": "z"}},
    )
    assert r.status_code == 409
    assert r.json()["detail"]["error"] == "match_full"


@pytest.mark.asyncio
async def test_snapshot_your_turn(client):
    a = await _create(client, "alpha")
    b = await _join(client, a["match_id"], "beta")
    mid = a["match_id"]

    snap = (await client.get(f"/api/matches/{mid}?seat=0")).json()
    assert snap["your_turn"] is True
    snap = (await client.get(f"/api/matches/{mid}?seat=1")).json()
    assert snap["your_turn"] is False


@pytest.mark.asyncio
async def test_legacy_claim_redirects(client):
    """Legacy `/matches/{id}/claim` HTML page was retired — it's now a 302
    to the interactive replay page `/match/{id}`. The plain-text variant
    (`claim.txt`) is still served for CLI consumers."""
    a = await _create(client, "p")
    await _join(client, a["match_id"], "q")
    mid = a["match_id"]

    await client.post(
        f"/api/matches/{mid}/action",
        headers={"X-Play-Token": a["play_token"]},
        json={"type": "place_stone", "x": 7, "y": 7},
    )

    r = await client.get(f"/matches/{mid}/claim", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"/match/{mid}"

    txt = await client.get(f"/matches/{mid}/claim.txt")
    assert txt.status_code == 200
    assert mid in txt.text
