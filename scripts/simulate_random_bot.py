#!/usr/bin/env python3
"""
Random-policy bot for Clawmoku. Use as sparring partner while developing.

Usage:
    # Create a new match and wait for opponent
    python scripts/simulate_random_bot.py --base http://127.0.0.1:9001 --create

    # Join an existing match
    python scripts/simulate_random_bot.py --base http://127.0.0.1:9001 --join <match_id>
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.error
import urllib.request
from typing import Any


def http_json(method: str, url: str, body: dict | None = None, headers: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"! HTTP {e.code}: {body}", file=sys.stderr)
        raise


def pick_move(stones: list[dict], board_size: int) -> tuple[int, int]:
    taken = {(s["x"], s["y"]) for s in stones}
    free = [
        (x, y)
        for y in range(board_size)
        for x in range(board_size)
        if (x, y) not in taken
    ]
    if not free:
        raise RuntimeError("board is full")
    # Prefer neighbors of existing stones for slightly more interesting play
    if stones:
        near = []
        for s in stones:
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == dy == 0:
                        continue
                    nx, ny = s["x"] + dx, s["y"] + dy
                    if (nx, ny) not in taken and 0 <= nx < board_size and 0 <= ny < board_size:
                        near.append((nx, ny))
        if near:
            return random.choice(near)
    return random.choice(free)


def play(base: str, match_id: str, seat: int, token: str) -> None:
    while True:
        snap = http_json("GET", f"{base}/api/matches/{match_id}?seat={seat}")
        status = snap["status"]
        if status == "finished":
            print(f"✔ finished: {snap['result']}")
            return
        if status == "waiting":
            time.sleep(1)
            continue
        if not snap.get("your_turn"):
            time.sleep(1)
            continue

        x, y = pick_move(snap["render"]["stones"], snap["render"]["board_size"])
        print(f"→ seat={seat} place ({x},{y})")
        try:
            resp = http_json(
                "POST",
                f"{base}/api/matches/{match_id}/action",
                body={"type": "place_stone", "x": x, "y": y},
                headers={"X-Play-Token": token},
            )
            if resp["status"] == "finished":
                print(f"✔ finished: {resp['result']}")
                return
        except urllib.error.HTTPError:
            time.sleep(1)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--base", default="http://127.0.0.1:9001")
    p.add_argument("--name", default=f"bot-{random.randint(1000,9999)}")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--create", action="store_true")
    group.add_argument("--join", metavar="MATCH_ID")
    args = p.parse_args()

    if args.create:
        resp = http_json(
            "POST",
            f"{args.base}/api/matches",
            body={
                "game": "gomoku",
                "config": {"turn_timeout": 120},
                "player": {"name": args.name, "display_name": args.name},
            },
        )
        print(f"created {resp['match_id']} invite={resp['invite_url']}")
        play(args.base, resp["match_id"], 0, resp["play_token"])
    else:
        resp = http_json(
            "POST",
            f"{args.base}/api/matches/{args.join}/join",
            body={"player": {"name": args.name, "display_name": args.name}},
        )
        print(f"joined {args.join} as seat {resp['seat']}")
        play(args.base, args.join, resp["seat"], resp["play_token"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
