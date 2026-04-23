"""Tests for lobby header stats + cursor-based pagination.

These power, respectively, the "近 24h 完赛 / 平均手数 / TOP Agent" strip
and the "加载更多完赛" button on the lobby page.
"""

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


async def _move(client, match_id, token, x, y):
    r = await client.post(
        f"/api/matches/{match_id}/action",
        headers={"X-Play-Token": token},
        json={"type": "place_stone", "x": x, "y": y},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _play_to_black_win(client, black_name: str, white_name: str) -> str:
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
async def test_today_stats_basic_shape(client):
    r = await client.get("/api/lobby/today_stats")
    assert r.status_code == 200
    body = r.json()
    # Contract: window + 6 numeric fields + top_agent placeholder.
    assert body["window_hours"] == 24
    for k in ("total", "longest", "decisive", "draws"):
        assert isinstance(body[k], int)
    assert isinstance(body["avg_moves"], (int, float))
    assert "top_agent" in body  # may be None on a clean window
    assert "since" in body


@pytest.mark.asyncio
async def test_today_stats_counts_recent_finishes(client):
    """A freshly-finished game should show up in the rolling window
    immediately and bump the decisive count by 1."""
    before = (await client.get("/api/lobby/today_stats")).json()

    await _play_to_black_win(client, "stat1A", "stat1B")

    after = (await client.get("/api/lobby/today_stats")).json()
    assert after["total"] == before["total"] + 1
    assert after["decisive"] == before["decisive"] + 1
    # `longest` is monotonically tracked; new game has 9 moves total
    # (5 black + 4 white before the closing move) so longest should be
    # >= the smaller of (previous longest, 9).
    assert after["longest"] >= min(before["longest"] or 9, 9)


@pytest.mark.asyncio
async def test_today_stats_window_query(client):
    # Hours bounds: 1..168 inclusive.
    assert (await client.get("/api/lobby/today_stats?hours=1")).status_code == 200
    assert (await client.get("/api/lobby/today_stats?hours=168")).status_code == 200
    # Out-of-bounds → 422 from FastAPI's query validator.
    assert (await client.get("/api/lobby/today_stats?hours=0")).status_code == 422
    assert (await client.get("/api/lobby/today_stats?hours=999")).status_code == 422


@pytest.mark.asyncio
async def test_finished_cursor_pagination(client):
    """Driving 3 finished games and paging with `before=<oldest_finished>`
    should return strictly older rows on the second page."""
    import asyncio
    from urllib.parse import quote

    ids = []
    for i in range(3):
        ids.append(await _play_to_black_win(client, f"pag{i}A", f"pag{i}B"))
        # Tiny gap so finished_at strictly differs.
        await asyncio.sleep(0.05)

    # Page 1: most recent first.
    r1 = await client.get("/api/matches?status=finished&limit=2")
    assert r1.status_code == 200
    page1 = r1.json()
    assert len(page1) == 2

    # Cursor = smallest finished_at on page 1 → next page is strictly
    # older. With 3 total + page size 2, page 2 should have 1 row.
    # `+` in the timezone offset must be percent-encoded — otherwise
    # the query parser turns it into a space and rejects the cursor.
    cursor = min(m["finished_at"] for m in page1)
    r2 = await client.get(
        f"/api/matches?status=finished&limit=2&before={quote(cursor)}"
    )
    assert r2.status_code == 200
    page2 = r2.json()

    # No id should appear on both pages.
    ids1 = {m["match_id"] for m in page1}
    ids2 = {m["match_id"] for m in page2}
    assert ids1.isdisjoint(ids2)

    # Every page-2 finished_at is strictly less than the cursor.
    for m in page2:
        assert m["finished_at"] < cursor


@pytest.mark.asyncio
async def test_invalid_cursor_rejected(client):
    r = await client.get("/api/matches?status=finished&before=not-a-timestamp")
    assert r.status_code == 400
    assert r.json()["detail"]["error"] == "invalid_cursor"
