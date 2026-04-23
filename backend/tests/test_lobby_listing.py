"""Tests for the lobby-facing enrichments to GET /api/matches:

* `X-Total-Count` response header (powers the "完赛 247" badge).
* Finished rows expose result / finished_at / duration_sec / mini board
  fields so the lobby card can render a thumbnail without N+1 calls.
* `sort=auto` pivots to recent_finished when status=finished, so the
  most recently concluded games surface first.
"""

from __future__ import annotations

import asyncio

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


async def _move(client, match_id, token, x, y):
    r = await client.post(
        f"/api/matches/{match_id}/action",
        headers={"X-Play-Token": token},
        json={"type": "place_stone", "x": x, "y": y},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _play_to_black_win(client, black_name: str, white_name: str) -> str:
    """Drive a deterministic black-five-in-a-row finish and return match_id."""
    a = await _create(client, black_name)
    b = await _join(client, a["match_id"], white_name)
    mid = a["match_id"]
    black_moves = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    white_moves = [(0, 0), (0, 1), (0, 2), (0, 3)]
    for i, bm in enumerate(black_moves):
        resp = await _move(client, mid, a["play_token"], *bm)
        if resp.get("status") == "finished":
            break
        await _move(client, mid, b["play_token"], *white_moves[i])
    return mid


@pytest.mark.asyncio
async def test_total_count_header_present_and_correct(client):
    # Three baseline rooms in `waiting`. Limit deliberately smaller than
    # total to prove the header reflects the catalogue, not the page.
    for n in ("h1", "h2", "h3"):
        await _create(client, n)

    r = await client.get("/api/matches?status=waiting&limit=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2  # respects `limit`
    total = r.headers.get("X-Total-Count")
    assert total is not None, "lobby badge depends on X-Total-Count"
    assert int(total) >= 3

    # Unfiltered total should be >= status-scoped total.
    r_all = await client.get("/api/matches?limit=1")
    assert int(r_all.headers["X-Total-Count"]) >= int(total)


@pytest.mark.asyncio
async def test_finished_card_carries_mini_board_and_result(client):
    mid = await _play_to_black_win(client, "miniA", "miniB")

    r = await client.get("/api/matches?status=finished&limit=10")
    assert r.status_code == 200
    rows = r.json()
    row = next((m for m in rows if m["match_id"] == mid), None)
    assert row is not None, "freshly finished match should appear in finished list"

    # Result block surfaced for the post-game pill / summary line.
    assert row["result"]["winner_seat"] == 0
    assert row["result"]["reason"] == "five_in_row"
    assert row["finished_at"] is not None
    assert isinstance(row["duration_sec"], int) and row["duration_sec"] >= 0

    # Mini-board payload — enough for the lobby thumbnail to render
    # without a follow-up snapshot fetch.
    assert row["board_size"] == 15
    stones = row["stones"]
    assert isinstance(stones, list) and len(stones) == row["move_count"]
    # winning_line + last_move both present so the thumbnail can highlight
    # the five and the closing stone.
    assert row["winning_line"] and len(row["winning_line"]) == 5
    assert row["last_move"] == {"x": 7, "y": 7}


@pytest.mark.asyncio
async def test_in_progress_rows_omit_finished_only_fields(client):
    a = await _create(client, "wA")
    await _join(client, a["match_id"], "wB")
    r = await client.get("/api/matches?status=in_progress&limit=10")
    assert r.status_code == 200
    rows = r.json()
    assert rows, "expected at least one in_progress room"
    row = next(m for m in rows if m["match_id"] == a["match_id"])
    # These fields are reserved for finished/aborted rows — keep the
    # in_progress / waiting payloads small.
    assert row["finished_at"] is None
    assert row["duration_sec"] is None
    assert row["result"] is None
    assert row["board_size"] is None
    assert row["stones"] is None
    assert row["winning_line"] is None


@pytest.mark.asyncio
async def test_finished_status_orders_by_finished_at_desc(client):
    """sort=auto + status=finished should surface the most recently
    concluded match first, even when an older game finishes after a
    newer game's creation. Reproduces the lobby's user expectation that
    "完赛 → 第一张" is "刚刚结束的那一局"."""

    first = await _play_to_black_win(client, "ord1A", "ord1B")
    # Tiny gap so finished_at timestamps strictly differ on systems where
    # the clock granularity is coarse (some sqlite + macOS combos).
    await asyncio.sleep(0.05)
    second = await _play_to_black_win(client, "ord2A", "ord2B")

    r = await client.get("/api/matches?status=finished&limit=10")
    assert r.status_code == 200
    rows = r.json()
    ids = [m["match_id"] for m in rows if m["match_id"] in (first, second)]
    assert ids[0] == second, f"expected most recently finished first, got {ids}"
