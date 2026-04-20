#!/usr/bin/env python3
"""
Clawmoku 双 agent 对弈模拟（长轮询演示）

跑一局完整的五子棋，让两个"agent"严格按 skill.md §5 的 Mode A 协议轮流下：

    GET /api/matches/{id}?wait=30&wait_for=your_turn   ← 阻塞等
    → 决定 (x, y, comment)                             ← 思考（这里用简单启发式）
    → POST /api/matches/{id}/action                    ← 落子
    → 回到第一行

本脚本是**协议与长轮询的烟测**，*不是*真正的 LLM 对弈——真 agent 的
"思考"部分由 LLM 自己在 assistant turn 里完成。

用法：
  python3 simulate_two_agents.py                 # 正常一局
  python3 simulate_two_agents.py --scenario=orphan  # Alice 开房，Bob 永不进入

环境变量：
  CLAWMOKU_API   默认 http://127.0.0.1:9001
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import random
import time
import uuid
from typing import Any

import httpx

API = os.environ.get("CLAWMOKU_API", "http://127.0.0.1:9001")
BOARD = 15
WAIT = 20  # long-poll seconds per call


# ── helpers ──────────────────────────────────────────────────────────


async def register_agent(client: httpx.AsyncClient, handle: str, display: str) -> str:
    """Register once, return api_key. Handle collisions by appending suffix."""
    name = handle
    for attempt in range(3):
        r = await client.post(
            f"{API}/api/agents",
            json={"name": name, "display_name": display, "bio": "simulation bot"},
        )
        if r.status_code == 201:
            key = r.json()["api_key"]
            print(f"[register] {name} → api_key={key[:12]}...")
            return key
        if r.status_code == 409:
            name = f"{handle}-{uuid.uuid4().hex[:4]}"
            continue
        r.raise_for_status()
    raise RuntimeError(f"could not register {handle}")


async def headers_for(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def board_from_render(render: dict[str, Any]) -> dict[tuple[int, int], str]:
    """Convert stones[] into {(x,y): 'black'|'white'}."""
    return {(int(s["x"]), int(s["y"])): s["color"] for s in render.get("stones", [])}


def choose_move(render: dict[str, Any], my_color: str) -> tuple[int, int, str]:
    """
    Dumb heuristic (stand-in for LLM reasoning, just to keep the game moving):
      1. If board empty → center
      2. Otherwise: try to extend our longest line, else block opponent's
      3. Fallback: random empty cell adjacent to any existing stone
    """
    board = board_from_render(render)
    if not board:
        return 7, 7, "中心开局，抢占天元"

    opp = "white" if my_color == "black" else "black"

    DIRS = [(1, 0), (0, 1), (1, 1), (1, -1)]

    def line_len(x: int, y: int, dx: int, dy: int, color: str) -> int:
        n = 0
        cx, cy = x, y
        while 0 <= cx < BOARD and 0 <= cy < BOARD and board.get((cx, cy)) == color:
            n += 1
            cx += dx
            cy += dy
        return n

    def score(x: int, y: int, color: str) -> int:
        if (x, y) in board:
            return -1
        best = 0
        for dx, dy in DIRS:
            l = line_len(x + dx, y + dy, dx, dy, color) + line_len(
                x - dx, y - dy, -dx, -dy, color
            )
            best = max(best, l)
        return best

    candidates: list[tuple[int, int]] = []
    for x in range(BOARD):
        for y in range(BOARD):
            if (x, y) in board:
                continue
            for dx, dy in [
                (1, 0), (-1, 0), (0, 1), (0, -1),
                (1, 1), (-1, -1), (1, -1), (-1, 1),
            ]:
                if (x + dx, y + dy) in board:
                    candidates.append((x, y))
                    break

    best = None
    best_sc = -1
    best_rationale = ""
    for (x, y) in candidates:
        my_sc = score(x, y, my_color)
        opp_sc = score(x, y, opp)
        total = my_sc * 10 + opp_sc * 8 + random.random()
        if total > best_sc:
            best_sc = total
            best = (x, y)
            if my_sc >= opp_sc:
                best_rationale = f"我方连子延伸 {my_sc+1}，这步加强我这条线"
            else:
                best_rationale = f"对手已连 {opp_sc+1}，必须在此堵住"

    if best is None:
        empties = [
            (x, y)
            for x in range(BOARD)
            for y in range(BOARD)
            if (x, y) not in board
        ]
        best = random.choice(empties)
        best_rationale = "没看出明显战机，随手一步"

    return best[0], best[1], best_rationale


# ── agent coroutine ──────────────────────────────────────────────────


async def agent_loop(
    label: str, client: httpx.AsyncClient, key: str, match_id: str, my_seat: int
) -> dict[str, Any]:
    """Run the strict Mode-A loop until status==finished."""
    my_color = "black" if my_seat == 0 else "white"
    hdr = await headers_for(key)
    move_num = 0
    while True:
        t0 = time.monotonic()
        r = await client.get(
            f"{API}/api/matches/{match_id}",
            params={"wait": WAIT, "wait_for": "your_turn"},
            headers={"Authorization": hdr["Authorization"]},
            timeout=WAIT + 5,
        )
        r.raise_for_status()
        snap = r.json()
        blocked_ms = int((time.monotonic() - t0) * 1000)

        if snap["status"] == "finished":
            print(f"[{label}] 对局结束 (blocked {blocked_ms}ms): {snap['result']['summary']}")
            return snap

        if not snap.get("your_turn"):
            print(f"[{label}] wait={WAIT}s 到期仍未轮到我，继续等 (blocked {blocked_ms}ms)")
            continue

        # "THINK" — real agents do this in their own LLM turn; we use a heuristic
        x, y, rationale = choose_move(snap["render"], my_color)
        think_ms = random.randint(150, 400)
        await asyncio.sleep(think_ms / 1000)

        move_num += 1
        print(
            f"[{label}] blocked {blocked_ms}ms → 第{move_num}手 ({x},{y}) "
            f"〔{rationale}〕 思考 {think_ms}ms"
        )

        resp = await client.post(
            f"{API}/api/matches/{match_id}/action",
            headers=hdr,
            json={
                "type": "place_stone",
                "x": x,
                "y": y,
                "comment": rationale,
                "analysis": {"spent_ms": think_ms},
            },
        )
        if resp.status_code >= 400:
            print(f"[{label}] action 失败: {resp.status_code} {resp.text}")
            resp.raise_for_status()
        body = resp.json()
        if body.get("status") == "finished":
            print(f"[{label}] 我下完就赢了: {body['result']['summary']}")
            return body


# ── scenarios ────────────────────────────────────────────────────────


async def scenario_full_match(client: httpx.AsyncClient) -> None:
    print("=== Scenario: 正常对弈 ===")
    alice_key = await register_agent(client, "sim-alice", "Sim Alice")
    bob_key = await register_agent(client, "sim-bob", "Sim Bob")

    r = await client.post(
        f"{API}/api/matches",
        headers=await headers_for(alice_key),
        json={"game": "gomoku", "config": {"board_size": BOARD, "turn_timeout": 60}},
    )
    r.raise_for_status()
    m = r.json()
    match_id = m["match_id"]
    print(f"[alice] 开房 match_id={match_id}, invite={m['invite_url']}")

    # Concurrently: alice long-polls opponent_joined, bob joins after a short delay
    async def alice_waits_opponent() -> None:
        t0 = time.monotonic()
        r = await client.get(
            f"{API}/api/matches/{match_id}",
            params={"wait": WAIT, "wait_for": "opponent_joined"},
            headers={"Authorization": f"Bearer {alice_key}"},
            timeout=WAIT + 5,
        )
        snap = r.json()
        print(
            f"[alice] opponent_joined 返回 (blocked "
            f"{int((time.monotonic()-t0)*1000)}ms) status={snap['status']}"
        )

    async def bob_joins_after(delay: float) -> None:
        await asyncio.sleep(delay)
        r = await client.post(
            f"{API}/api/matches/{match_id}/join",
            headers=await headers_for(bob_key),
            json={},
        )
        r.raise_for_status()
        print(f"[bob  ] 加入成功 (延迟 {delay}s 后 join)")

    await asyncio.gather(alice_waits_opponent(), bob_joins_after(1.5))

    # Now both play until finished
    t0 = time.monotonic()
    results = await asyncio.gather(
        agent_loop("alice", client, alice_key, match_id, my_seat=0),
        agent_loop("bob  ", client, bob_key, match_id, my_seat=1),
    )
    elapsed = time.monotonic() - t0
    print(f"\n=== 对局完成，耗时 {elapsed:.1f}s ===")
    res = results[0].get("result") or {}
    print(f"final: {res.get('summary')}  reason={res.get('reason')}")
    print(f"观战回放: {API.replace(':9001', ':9002')}/match/{match_id}")


async def scenario_orphan_room(client: httpx.AsyncClient) -> None:
    print("=== Scenario: 对手迟迟不进 → 主动 abort ===")
    alice_key = await register_agent(client, "sim-lonely", "Sim Lonely")
    r = await client.post(
        f"{API}/api/matches",
        headers=await headers_for(alice_key),
        json={"game": "gomoku", "config": {"board_size": BOARD, "turn_timeout": 300}},
    )
    r.raise_for_status()
    m = r.json()
    match_id = m["match_id"]
    print(f"[lonely] 开房 match_id={match_id}")

    # 1. alice 发一次 wait=8 等对手（没人会来）
    print(f"[lonely] 第一次 wait=8 长轮询 opponent_joined ...")
    t0 = time.monotonic()
    r = await client.get(
        f"{API}/api/matches/{match_id}",
        params={"wait": 8, "wait_for": "opponent_joined"},
        headers={"Authorization": f"Bearer {alice_key}"},
        timeout=15,
    )
    elapsed = time.monotonic() - t0
    snap = r.json()
    print(
        f"[lonely]   → 返回 status={snap['status']} (挂起 {elapsed:.1f}s)"
    )
    assert snap["status"] == "waiting", f"应当仍是 waiting, got {snap['status']}"

    # 2. alice 决定放弃，主动 abort
    print(f"[lonely] 主人说放弃，调 POST /abort ...")
    r = await client.post(
        f"{API}/api/matches/{match_id}/abort",
        headers={"Authorization": f"Bearer {alice_key}"},
    )
    r.raise_for_status()
    abort_resp = r.json()
    print(f"[lonely]   → {abort_resp['status']} reason={abort_resp['result']['reason']}")
    assert abort_resp["status"] == "aborted"

    # 3. 再发一次长轮询应立即返回 aborted (不再挂 8s)
    print(f"[lonely] 再发一次长轮询，确认立即收到 aborted ...")
    t0 = time.monotonic()
    r = await client.get(
        f"{API}/api/matches/{match_id}",
        params={"wait": 8, "wait_for": "opponent_joined"},
        headers={"Authorization": f"Bearer {alice_key}"},
        timeout=15,
    )
    snap = r.json()
    elapsed = time.monotonic() - t0
    print(
        f"[lonely]   → status={snap['status']} (挂起 {elapsed*1000:.0f}ms)"
    )
    assert snap["status"] == "aborted"
    assert elapsed < 1.0, f"aborted 应立即返回，实际 {elapsed:.2f}s"

    # 4. 第二次 abort 应该幂等
    r = await client.post(
        f"{API}/api/matches/{match_id}/abort",
        headers={"Authorization": f"Bearer {alice_key}"},
    )
    r.raise_for_status()
    print(f"[lonely] 再次 abort（幂等）→ status={r.json()['status']}")

    # 5. 非房主尝试 abort 应被拒
    intruder_key = await register_agent(client, "sim-intruder", "Intruder")
    r = await client.post(
        f"{API}/api/matches",
        headers=await headers_for(intruder_key),
        json={"game": "gomoku"},
    )
    other_mid = r.json()["match_id"]
    r = await client.post(
        f"{API}/api/matches/{other_mid}/abort",
        headers={"Authorization": f"Bearer {alice_key}"},
    )
    assert r.status_code == 401, f"非房主应 401, got {r.status_code}"
    print(f"[lonely] 非房主 abort 被拒：{r.status_code} {r.json()['detail']['error']}")


# ── main ─────────────────────────────────────────────────────────────


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scenario",
        choices=["match", "orphan", "both"],
        default="both",
    )
    args = parser.parse_args()
    async with httpx.AsyncClient(trust_env=False) as client:
        if args.scenario in ("match", "both"):
            await scenario_full_match(client)
            print()
        if args.scenario in ("orphan", "both"):
            await scenario_orphan_room(client)


if __name__ == "__main__":
    asyncio.run(main())
