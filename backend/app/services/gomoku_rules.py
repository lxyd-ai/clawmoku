"""
Pure gomoku rules: stateless functions operating on a dict-based `state`.

state schema:
    {
        "board_size": int,
        "board": list[list[int]],   # 0 empty, 1 black (seat 0), 2 white (seat 1)
        "current_seat": int,
        "move_count": int,
        "move_history": [{seq, seat, x, y}, ...],
        "last_move": {x, y} | None,
        "winning_line": list[{x,y}] | None,
    }
"""

from __future__ import annotations

from typing import Any

DIRECTIONS = [(1, 0), (0, 1), (1, 1), (1, -1)]


class InvalidMove(Exception):
    """Raised when a move violates rules (out of bounds, occupied, etc)."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def empty_state(board_size: int = 15) -> dict[str, Any]:
    size = max(9, min(19, int(board_size)))
    return {
        "board_size": size,
        "board": [[0] * size for _ in range(size)],
        "current_seat": 0,
        "move_count": 0,
        "move_history": [],
        "last_move": None,
        "winning_line": None,
    }


def _check_win(board: list[list[int]], x: int, y: int, player: int, size: int) -> list[dict] | None:
    for dx, dy in DIRECTIONS:
        line = [{"x": x, "y": y}]
        for sign in (1, -1):
            for step in range(1, 5):
                nx, ny = x + dx * sign * step, y + dy * sign * step
                if 0 <= nx < size and 0 <= ny < size and board[ny][nx] == player:
                    line.append({"x": nx, "y": ny})
                else:
                    break
        if len(line) >= 5:
            line.sort(key=lambda p: (p["x"], p["y"]))
            return line[:5]
    return None


def _is_draw(board: list[list[int]], size: int) -> bool:
    return all(board[y][x] != 0 for y in range(size) for x in range(size))


def apply_move(state: dict[str, Any], seat: int, x: int, y: int) -> dict[str, Any]:
    """
    Apply a move and return a new state dict plus an `outcome` summary.

    Returns:
        {
            "state": <new state>,
            "status": "in_progress" | "finished",
            "result": {winner_seat, reason, summary} | None,
        }
    """
    if state.get("winning_line"):
        raise InvalidMove("match_finished", "对局已结束")
    if seat != state["current_seat"]:
        raise InvalidMove("not_your_turn", f"当前轮到 seat {state['current_seat']}")

    size = state["board_size"]
    if not (0 <= x < size and 0 <= y < size):
        raise InvalidMove("invalid_move", f"坐标越界: ({x},{y})")
    # deep-ish copy (board is nested list of ints)
    board = [row[:] for row in state["board"]]
    if board[y][x] != 0:
        raise InvalidMove("invalid_move", f"位置 ({x},{y}) 已有棋子")

    player = seat + 1  # seat 0 -> 1 (black), seat 1 -> 2 (white)
    board[y][x] = player
    move_count = state["move_count"] + 1
    history = list(state["move_history"])
    history.append({"seq": move_count, "seat": seat, "x": x, "y": y})

    new_state = {
        "board_size": size,
        "board": board,
        "current_seat": 1 - seat,
        "move_count": move_count,
        "move_history": history,
        "last_move": {"x": x, "y": y},
        "winning_line": None,
    }

    winning_line = _check_win(board, x, y, player, size)
    if winning_line:
        new_state["winning_line"] = winning_line
        winner_color = "黑" if seat == 0 else "白"
        return {
            "state": new_state,
            "status": "finished",
            "result": {
                "winner_seat": seat,
                "reason": "five_in_row",
                "summary": f"{winner_color}方 第 {move_count} 手获胜",
            },
        }

    if _is_draw(board, size):
        return {
            "state": new_state,
            "status": "finished",
            "result": {
                "winner_seat": None,
                "reason": "draw",
                "summary": "棋盘已满，平局",
            },
        }

    return {"state": new_state, "status": "in_progress", "result": None}


def render_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    """Turn internal state into the `render` block defined in the protocol."""
    size = state["board_size"]
    board = state["board"]
    stones = []
    for y in range(size):
        for x in range(size):
            v = board[y][x]
            if v:
                stones.append(
                    {"x": x, "y": y, "color": "black" if v == 1 else "white"}
                )
    # attach seq from move_history for deterministic ordering
    seq_by_xy = {(m["x"], m["y"]): m["seq"] for m in state.get("move_history", [])}
    for s in stones:
        s["seq"] = seq_by_xy.get((s["x"], s["y"]), 0)
    stones.sort(key=lambda s: s["seq"])
    return {
        "board_size": size,
        "stones": stones,
        "last_move": state.get("last_move"),
        "winning_line": state.get("winning_line"),
        "move_count": state.get("move_count", 0),
    }


def ascii_board(state: dict[str, Any]) -> str:
    """Used by the /claim page and debug output."""
    size = state["board_size"]
    board = state["board"]
    cols = [chr(ord("A") + i) for i in range(size)]
    rows = ["   " + " ".join(cols)]
    symbol = {0: ".", 1: "X", 2: "O"}
    for y in range(size):
        cells = " ".join(symbol[board[y][x]] for x in range(size))
        rows.append(f"{y + 1:2d} {cells}")
    return "\n".join(rows)
