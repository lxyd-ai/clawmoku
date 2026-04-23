#!/usr/bin/env python3
"""
通用五子棋陪练 Bot（虾聊竞技场）

用法:
  CLAWD_KEY=xxx AGENT_NAME=CursorClaw python3 arena_sparring.py

环境变量:
  CLAWD_KEY            API Key（必须）
  AGENT_NAME           Agent 名称，用于识别自己的颜色（必须）
  VERBOSE=1            每局结束打一行 json 到 stdout
  MATCH_ID=            从指定房开始，否则先开新局
  THINK_MIN=10         模拟思考最短秒数（默认 10）
  THINK_MAX=20         模拟思考最长秒数（默认 20）
  REST_MIN=30          局间休息最短秒数（默认 30）
  REST_MAX=60          局间休息最长秒数（默认 60）
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request

BRAIN_VERSION = os.environ.get("BRAIN", "v4").strip().lower()
try:
    if BRAIN_VERSION == "v6":
        sys.path.insert(0, "/Users/xiexinfa/demo/clawmoku/scripts")
        from brain_v6 import GomokuBrainV6 as GomokuBrainV2
    elif BRAIN_VERSION == "v5":
        sys.path.insert(0, "/Users/xiexinfa/demo/clawmoku/scripts")
        from brain_v5 import GomokuBrainV5 as GomokuBrainV2
    else:
        sys.path.insert(0, "/Users/xiexinfa/.cursor/skills/clawmoku-gomoku/scripts")
        from brain import GomokuBrainV2
except Exception as e:
    print(f"brain import failed (version={BRAIN_VERSION}):", e, file=sys.stderr)
    raise SystemExit(1)

CLAWD_KEY = (os.environ.get("CLAWD_KEY") or "").strip()
AGENT_NAME = (os.environ.get("AGENT_NAME") or "").strip()
if not CLAWD_KEY or not AGENT_NAME:
    print("Usage: CLAWD_KEY=xxx AGENT_NAME=xxx python3 arena_sparring.py", file=sys.stderr)
    raise SystemExit(1)

# 小写化的 handle 匹配串（兼容 name@clawdchat 格式）
MATCH_NAMES = {AGENT_NAME.lower(), f"{AGENT_NAME.lower()}@clawdchat"}

UA = f"{AGENT_NAME}Sparring/1.0"
BASE = "https://clawdchat.cn/api/v1/arena/gomoku/matches"
VERBOSE = os.environ.get("VERBOSE", "").strip() in ("1", "true", "yes")
THINK_MIN = float(os.environ.get("THINK_MIN", "10"))
THINK_MAX = float(os.environ.get("THINK_MAX", "20"))
REST_MIN = float(os.environ.get("REST_MIN", "30"))
REST_MAX = float(os.environ.get("REST_MAX", "60"))


def _log(obj: dict) -> None:
    if VERBOSE:
        obj["bot"] = AGENT_NAME
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
            if e.code in (502, 503, 504, 429, 409):
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
    w = min(60, max(1, wait))
    q = f"{BASE}/{match_id}?wait={w}&wait_for={wait_for}"
    return http_json("GET", q)


def my_color(snap: dict) -> str:
    for p in snap.get("players") or []:
        n = (p.get("name") or "").lower()
        if n in MATCH_NAMES:
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
        # 模拟思考延时
        target = random.uniform(THINK_MIN, THINK_MAX)
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
    _log({"phase": "start", "think": f"{THINK_MIN}-{THINK_MAX}s", "rest": f"{REST_MIN}-{REST_MAX}s"})
    match_id = (os.environ.get("MATCH_ID") or "").strip()
    if not match_id:
        c = create_match()
        match_id = c.get("match_id", "")
        _log({"phase": "created", "match_id": match_id, "invite_url": c.get("invite_url")})
    if not match_id:
        print("no match_id", file=sys.stderr)
        raise SystemExit(1)

    while True:
        play_one_match(match_id)
        gap = random.uniform(REST_MIN, REST_MAX)
        _log({"phase": "resting", "seconds": round(gap, 1)})
        time.sleep(gap)
        c = create_match()
        match_id = c.get("match_id", "")
        _log({"phase": "new_room", "match_id": match_id, "invite_url": c.get("invite_url")})
        if not match_id:
            time.sleep(5)


if __name__ == "__main__":
    main()
