from __future__ import annotations

import pytest

from app.services.gomoku_rules import (
    InvalidMove,
    apply_move,
    empty_state,
    render_snapshot,
)


def test_first_move_center():
    s = empty_state(15)
    out = apply_move(s, 0, 7, 7)
    assert out["status"] == "in_progress"
    assert out["state"]["current_seat"] == 1
    assert out["state"]["move_count"] == 1


def test_rejects_wrong_turn():
    s = empty_state()
    with pytest.raises(InvalidMove) as exc:
        apply_move(s, 1, 7, 7)
    assert exc.value.code == "not_your_turn"


def test_rejects_out_of_bounds():
    s = empty_state(15)
    with pytest.raises(InvalidMove) as exc:
        apply_move(s, 0, 99, 7)
    assert exc.value.code == "invalid_move"


def test_rejects_occupied():
    s = empty_state()
    s = apply_move(s, 0, 7, 7)["state"]
    s = apply_move(s, 1, 8, 8)["state"]
    with pytest.raises(InvalidMove) as exc:
        apply_move(s, 0, 7, 7)
    assert exc.value.code == "invalid_move"


def test_horizontal_five_wins():
    s = empty_state(15)
    # black plays 5 in a row at y=7; white plays elsewhere
    black_moves = [(3, 7), (4, 7), (5, 7), (6, 7), (7, 7)]
    white_moves = [(0, 0), (0, 1), (0, 2), (0, 3)]
    outcome = None
    for i, (bx, by) in enumerate(black_moves):
        outcome = apply_move(s, 0, bx, by)
        s = outcome["state"]
        if outcome["status"] == "finished":
            break
        wx, wy = white_moves[i]
        s = apply_move(s, 1, wx, wy)["state"]

    assert outcome["status"] == "finished"
    assert outcome["result"]["winner_seat"] == 0
    assert outcome["result"]["reason"] == "five_in_row"


def test_diagonal_five_wins():
    s = empty_state(15)
    black = [(3, 3), (4, 4), (5, 5), (6, 6), (7, 7)]
    white = [(0, 14), (1, 14), (2, 14), (3, 14)]
    outcome = None
    for i, (bx, by) in enumerate(black):
        outcome = apply_move(s, 0, bx, by)
        s = outcome["state"]
        if outcome["status"] == "finished":
            break
        wx, wy = white[i]
        s = apply_move(s, 1, wx, wy)["state"]
    assert outcome["status"] == "finished"
    assert outcome["result"]["winner_seat"] == 0


def test_render_stones_sorted_by_seq():
    s = empty_state(15)
    for i, (x, y, seat) in enumerate(
        [(7, 7, 0), (8, 8, 1), (7, 8, 0), (8, 7, 1)]
    ):
        s = apply_move(s, seat, x, y)["state"]
    r = render_snapshot(s)
    assert [st["seq"] for st in r["stones"]] == [1, 2, 3, 4]
    assert r["last_move"] == {"x": 8, "y": 7}
