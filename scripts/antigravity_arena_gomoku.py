#!/usr/bin/env python3
"""
Antigravity — Clawmoku 陪练（虾聊竞技场全代理）
参考 /tmp/cursorclaw_arena_gomoku.py；默认静默（仅 stderr 致命错误）

凭证（优先顺序）:
  1) 环境变量 CLAWD_KEY
  2) 文件 ~/.clawmoku/antigravity_arena_key  （单行长 key，chmod 600）

环境:
  VERBOSE=1          每局结束打一行 json 到 stdout
  MATCH_ID=          从指定房开始，否则先开新局
  ARENA_THINK_JITTER=1  落子前随机等待 15–25s（与参考脚本一致）；默认 0 最响应
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

KEY_FILE = os.path.expanduser("~/.clawmoku/antigravity_arena_key")

try:
    sys.path.insert(0, "/Users/xiexinfa/.cursor/skills/clawmoku-gomoku/scripts")
    from brain import GomokuBrainV2
except Exception as e:
    print("brain import failed:", e, file=sys.stderr)
    raise SystemExit(1)

CLAWD_KEY = (os.environ.get("CLAWD_KEY") or "").strip()
if not CLAWD_KEY and os.path.isfile(KEY_FILE):
    try:
        CLAWD_KEY = open(KEY_FILE, encoding="utf-8").read().strip()
    except OSError:
        pass
if not CLAWD_KEY:
    print("Set CLAWD_KEY or create ~/.clawmoku/antigravity_arena_key", file=sys.stderr)
    raise SystemExit(1)

UA = "AntigravitySparring/1.0"
BASE = "https://clawdchat.cn/api/v1/arena/gomoku/matches"
VERBOSE = os.environ.get("VERBOSE", "").strip() in ("1", "true", "yes")
THINK_JITTER = os.environ.get("ARENA_THINK_JITTER", "1").strip() not in ("0", "false", "no")
# 虾聊 handle 一般为小写 @clawdchat
MY_NAME = (os.environ.get("ARENA_AGENT_HANDLE", "antigravity@clawdchat") or "").lower()


def _log(obj: dict) -> None:
    if VERBOSE:
        print(json.dumps(obj, ensure_ascii=False), flush=True)


def http_json(method: str, url: str, body: dict | None = None) -> dict:
    h: dict = {
        "Authorization": f"Bearer {CLAWD_KEY}",
        "User-Agent": UA,
    }
    data: bytes | None = None
    if body is not None:
        h["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    while True:
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=h)
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504, 429):
                time.sleep(60)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(30)
            continue


def create_match() -> dict:
    body = {"config": {"board_size": 15, "turn_timeout": 120}}
    return http_json("POST", BASE, body)


def get_snap(match_id: str, wait: int, wait_for: str) -> dict:
    # wait 必须 <=60（虾聊代理）
    w = min(60, max(1, wait))
    q = f"{BASE}/{match_id}?wait={w}&wait_for={wait_for}"
    return http_json("GET", q)


def my_color(snap: dict) -> str:
    for p in snap.get("players") or []:
        n = (p.get("name") or "").lower()
        if n == MY_NAME or "antigravity" in n:
            return "black" if p.get("seat") == 0 else "white"
    return "black"


def play_one_match(match_id: str) -> dict | None:
    s: dict = {}
    for _ in range(240):
        s = get_snap(match_id, 60, "opponent_joined")
        st = s.get("status")
        if st == "in_progress":
            break
        if st in ("aborted", "finished"):
            _log({"phase": "room_end", "status": st, "match_id": match_id})
            return s
    else:
        _log({"phase": "opponent_wait_timeout", "match_id": match_id})
        return None

    color = my_color(s)
    _log({"phase": "play", "color": color, "match_id": match_id})

    while True:
        s = get_snap(match_id, 60, "your_turn")
        if s.get("status") == "finished":
            _log({"phase": "finished", "match_id": match_id, "result": s.get("result")})
            return s
        if not s.get("your_turn"):
            continue
        stones = s.get("render", {}).get("stones") or []
        arr = [
            {"x": x["x"], "y": x["y"], "color": x.get("color", "black")} for x in stones
        ]
        think_start = time.time()
        brain = GomokuBrainV2(arr)
        x, y, comment = brain.think(color)
        if THINK_JITTER:
            target = random.uniform(15.0, 25.0)
            elapsed = time.time() - think_start
            if target - elapsed > 0:
                time.sleep(target - elapsed)
        spent = int((time.time() - think_start) * 1000)
        body = {
            "type": "place_stone",
            "x": int(x),
            "y": int(y),
            "comment": (comment or "")[:500],
            "analysis": {"eval": 0.0, "spent_ms": spent},
        }
        r = http_json("POST", f"{BASE}/{match_id}/action", body)
        if not r.get("accepted", r.get("success", True)):
            time.sleep(2)


def main() -> None:
    match_id = (os.environ.get("MATCH_ID") or "").strip()
    if not match_id:
        c = create_match()
        match_id = c.get("match_id", "")
        _log(
            {
                "phase": "created",
                "match_id": match_id,
                "invite_url": c.get("invite_url"),
            }
        )
    if not match_id:
        print("no match_id", file=sys.stderr)
        raise SystemExit(1)

    while True:
        play_one_match(match_id)
        # 局间休息 30-60 秒，模拟自然节奏
        gap = random.uniform(30, 60)
        _log({"phase": "resting", "seconds": round(gap, 1)})
        time.sleep(gap)
        c = create_match()
        match_id = c.get("match_id", "")
        _log(
            {
                "phase": "new_room",
                "match_id": match_id,
                "invite_url": c.get("invite_url"),
            }
        )
        if not match_id:
            time.sleep(5)


if __name__ == "__main__":
    main()
