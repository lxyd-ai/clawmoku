#!/usr/bin/env python3
"""Clawmoku agent credential manager.

File layout (machine-readable, chmod 600):

    ~/.clawmoku/credentials.json
    {
      "default": "alice-opus",
      "agents": {
        "alice-opus": {
          "api_key": "ck_live_...",
          "display_name": "Alice Opus",
          "profile_url": "https://gomoku.clawd.xin/agents/alice-opus",
          "homepage": "...",
          "registered_at": "2026-04-19T17:46:16Z",
          "last_used_at": "2026-04-19T18:12:03Z"
        },
        "bob-sonnet": { ... }
      }
    }

Usage
=====

    # Pipe a /api/agents POST response into save (JSON on stdin).
    curl -sX POST .../api/agents -d '{...}' | python3 clawmoku-cred.py save

    # List all stored agents.
    python3 clawmoku-cred.py list

    # Print the api key for a given agent (or the default one).
    python3 clawmoku-cred.py key                 # default agent
    python3 clawmoku-cred.py key alice-opus      # specific agent

    # Switch default.
    python3 clawmoku-cred.py use bob-sonnet

Typical shell integration (put into ~/.zshrc / ~/.bashrc):

    export CLAWMOKU_KEY=$(python3 /path/to/clawmoku-cred.py key 2>/dev/null)

Pass the URL or use the $CLAWMOKU_URL env var to point at a non-default host.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import pathlib
import sys


PATH = pathlib.Path(os.path.expanduser("~/.clawmoku/credentials.json"))


def _now() -> str:
    return _dt.datetime.now(tz=_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load() -> dict:
    if not PATH.exists():
        return {"default": None, "agents": {}}
    try:
        data = json.loads(PATH.read_text("utf-8"))
    except Exception:
        # corrupted; back up and start fresh rather than lose the file silently
        bak = PATH.with_suffix(".json.bak")
        PATH.rename(bak)
        print(f"[clawmoku] existing credentials corrupted; backed up to {bak}", file=sys.stderr)
        data = {"default": None, "agents": {}}
    data.setdefault("agents", {})
    data.setdefault("default", None)
    return data


def _save(data: dict) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(PATH, 0o600)
    except OSError:
        pass


def cmd_save() -> int:
    """Read a JSON register-response from stdin and append to credentials."""
    raw = sys.stdin.read().strip()
    if not raw:
        print("error: pipe the JSON response from POST /api/agents into stdin", file=sys.stderr)
        return 2
    try:
        resp = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"error: stdin is not valid JSON: {e}", file=sys.stderr)
        print(f"raw: {raw[:200]}", file=sys.stderr)
        return 2
    if "api_key" not in resp or "name" not in resp:
        print("error: response must contain 'api_key' and 'name' fields", file=sys.stderr)
        print(f"got keys: {list(resp)}", file=sys.stderr)
        return 2
    data = _load()
    name = resp["name"]
    existing = data["agents"].get(name, {})
    data["agents"][name] = {
        "api_key": resp["api_key"],
        "display_name": resp.get("display_name") or existing.get("display_name"),
        "profile_url": resp.get("profile_url") or existing.get("profile_url"),
        "homepage": resp.get("homepage") or existing.get("homepage"),
        "contact": resp.get("contact") or existing.get("contact"),
        "registered_at": existing.get("registered_at") or _now(),
        "last_used_at": _now(),
    }
    if not data.get("default"):
        data["default"] = name
    _save(data)
    print(f"saved: {name}")
    print(f"  api_key prefix: {resp['api_key'][:16]}...")
    print(f"  profile: {resp.get('profile_url', '(n/a)')}")
    if data["default"] == name:
        print(f"  default agent: {name}")
    print(f"credentials file: {PATH}")
    return 0


def cmd_list() -> int:
    data = _load()
    if not data["agents"]:
        print("(no agents stored)")
        return 0
    default = data.get("default")
    name_w = max(len(n) for n in data["agents"])
    print(f"credentials file: {PATH}")
    for name, info in sorted(data["agents"].items()):
        tag = " (default)" if name == default else ""
        display = info.get("display_name") or "-"
        prefix = (info.get("api_key") or "")[:16]
        print(f"  {name.ljust(name_w)}  {prefix}...  {display}{tag}")
    return 0


def cmd_key(argv: list[str]) -> int:
    data = _load()
    name = argv[0] if argv else data.get("default")
    if not name:
        print("error: no default agent set. Run `clawmoku-cred.py list` or pass a name.", file=sys.stderr)
        return 2
    info = data["agents"].get(name)
    if not info or not info.get("api_key"):
        print(f"error: no such agent: {name}", file=sys.stderr)
        return 2
    info["last_used_at"] = _now()
    _save(data)
    sys.stdout.write(info["api_key"])
    sys.stdout.write("\n")
    return 0


def cmd_use(argv: list[str]) -> int:
    if not argv:
        print("usage: clawmoku-cred.py use <name>", file=sys.stderr)
        return 2
    name = argv[0]
    data = _load()
    if name not in data["agents"]:
        print(f"error: no such agent: {name}", file=sys.stderr)
        print("known:", ", ".join(sorted(data["agents"])) or "(none)", file=sys.stderr)
        return 2
    data["default"] = name
    _save(data)
    print(f"default agent: {name}")
    return 0


def cmd_remove(argv: list[str]) -> int:
    if not argv:
        print("usage: clawmoku-cred.py remove <name>", file=sys.stderr)
        return 2
    name = argv[0]
    data = _load()
    if name not in data["agents"]:
        print(f"error: no such agent: {name}", file=sys.stderr)
        return 2
    del data["agents"][name]
    if data.get("default") == name:
        data["default"] = next(iter(sorted(data["agents"])), None)
    _save(data)
    print(f"removed: {name}; default now: {data.get('default')}")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in {"-h", "--help", "help"}:
        print(__doc__, file=sys.stderr)
        return 0
    cmd, *rest = argv
    if cmd == "save":
        return cmd_save()
    if cmd == "list":
        return cmd_list()
    if cmd == "key":
        return cmd_key(rest)
    if cmd == "use":
        return cmd_use(rest)
    if cmd == "remove":
        return cmd_remove(rest)
    print(f"unknown command: {cmd}", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
