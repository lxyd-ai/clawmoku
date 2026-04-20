"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";

import { Board, type Stone } from "./board";
import { CommentaryStream, type MoveEntry } from "./commentary-stream";

type Player = {
  seat: number;
  name: string;
  display_name?: string | null;
};

type Props = {
  matchId: string;
  boardSize: number;
  players: Player[];
  moves: MoveEntry[];
  result: null | {
    winner_seat: number | null;
    reason: string;
    summary: string;
  };
  /** Optional winning_line drawn on the board at final position. */
  winningLine?: { x: number; y: number }[] | null;
};

const SPEEDS = [0.5, 1, 2, 4] as const;

export function ReplayClient({
  matchId,
  boardSize,
  players,
  moves,
  result,
  winningLine,
}: Props) {
  const total = moves.length;
  // cursor is the number of moves currently shown. 0 = empty board, total = final.
  const [cursor, setCursor] = useState<number>(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<(typeof SPEEDS)[number]>(1);

  // Reset cursor when moves list changes (e.g., page re-mount).
  useEffect(() => {
    setCursor(0);
    setPlaying(false);
  }, [matchId]);

  // Autoplay: advance one move every `interval` ms.
  useEffect(() => {
    if (!playing) return;
    if (cursor >= total) {
      setPlaying(false);
      return;
    }
    const base = 1000;
    const interval = Math.max(120, base / speed);
    const h = setTimeout(() => setCursor((c) => Math.min(total, c + 1)), interval);
    return () => clearTimeout(h);
  }, [playing, cursor, total, speed]);

  // Keyboard shortcuts.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement | null)?.tagName?.toLowerCase();
      if (tag === "input" || tag === "textarea") return;
      switch (e.key) {
        case " ":
          e.preventDefault();
          setPlaying((p) => !p);
          break;
        case "ArrowRight":
          e.preventDefault();
          setCursor((c) => Math.min(total, c + 1));
          break;
        case "ArrowLeft":
          e.preventDefault();
          setCursor((c) => Math.max(0, c - 1));
          break;
        case "Home":
          e.preventDefault();
          setCursor(0);
          break;
        case "End":
          e.preventDefault();
          setCursor(total);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [total]);

  const visibleStones: Stone[] = useMemo(() => {
    return moves.slice(0, cursor).map((m) => ({
      x: m.x,
      y: m.y,
      color: m.color,
      seq: m.move_number,
    }));
  }, [moves, cursor]);

  const lastMove = cursor > 0 ? moves[cursor - 1] : null;

  // winning line only at full cursor
  const showWinning =
    cursor === total && winningLine && winningLine.length > 0
      ? winningLine
      : undefined;

  const highlightMoveNumber = cursor > 0 ? cursor : null;

  const handleSelect = useCallback((moveNumber: number) => {
    setCursor(moveNumber);
    setPlaying(false);
  }, []);

  const black = players.find((p) => p.seat === 0);
  const white = players.find((p) => p.seat === 1);
  const winner = result?.winner_seat != null
    ? players.find((p) => p.seat === result.winner_seat)
    : null;

  return (
    <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_340px]">
      <div className="space-y-4">
        {/* mini header */}
        <div className="flex items-center justify-between rounded-2xl border border-wood-100 bg-white px-4 py-3 shadow-soft">
          <div className="text-sm">
            <div className="flex items-center gap-2">
              <span className="stone-b" aria-hidden />
              <span className="font-medium text-ink-800">
                {black?.display_name || black?.name || "黑方"}
              </span>
              <span className="text-ink-400">vs</span>
              <span className="font-medium text-ink-800">
                {white?.display_name || white?.name || "白方"}
              </span>
              <span className="stone-w" aria-hidden />
            </div>
            <div className="mt-0.5 text-[11px] uppercase tracking-widest text-ink-500">
              回放模式
              {result?.reason && (
                <span className="ml-2 rounded-full bg-ink-900/5 px-1.5 py-0.5 text-[10px]">
                  {result.reason}
                </span>
              )}
            </div>
          </div>
          <div className="text-right">
            <div className="font-display text-xl tabular-nums text-ink-900">
              {cursor} / {total}
            </div>
            {lastMove?.comment && (
              <div className="mt-0.5 max-w-xs truncate text-[11px] text-ink-500">
                "{lastMove.comment}"
              </div>
            )}
          </div>
        </div>

        <Board
          size={boardSize}
          stones={visibleStones}
          lastMove={lastMove ? { x: lastMove.x, y: lastMove.y } : null}
          winningLine={showWinning}
        />

        {/* Transport controls */}
        <div className="rounded-2xl border border-wood-100 bg-white p-4 shadow-soft">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setCursor(0);
                setPlaying(false);
              }}
              className="rounded-lg border border-wood-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-cream-50"
              title="跳到开局 (Home)"
            >
              ⏮
            </button>
            <button
              type="button"
              onClick={() => setCursor((c) => Math.max(0, c - 1))}
              className="rounded-lg border border-wood-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-cream-50"
              title="上一手 (←)"
            >
              ⏪
            </button>
            <button
              type="button"
              onClick={() => {
                if (cursor >= total) setCursor(0);
                setPlaying((p) => !p);
              }}
              className="rounded-lg bg-accent-600 px-4 py-1.5 text-sm font-medium text-white shadow-soft hover:bg-accent-700"
              title="播放/暂停 (Space)"
            >
              {playing ? "⏸ 暂停" : cursor >= total ? "↻ 重播" : "▶ 播放"}
            </button>
            <button
              type="button"
              onClick={() => setCursor((c) => Math.min(total, c + 1))}
              className="rounded-lg border border-wood-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-cream-50"
              title="下一手 (→)"
            >
              ⏩
            </button>
            <button
              type="button"
              onClick={() => {
                setCursor(total);
                setPlaying(false);
              }}
              className="rounded-lg border border-wood-200 bg-white px-3 py-1.5 text-sm text-ink-700 hover:bg-cream-50"
              title="跳到终局 (End)"
            >
              ⏭
            </button>
            <div className="ml-auto flex items-center gap-1 text-xs text-ink-500">
              <span>速度</span>
              {SPEEDS.map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSpeed(s)}
                  className={`rounded-md border px-2 py-0.5 font-mono ${
                    speed === s
                      ? "border-accent-500 bg-accent-50 text-accent-700"
                      : "border-wood-200 bg-white text-ink-600 hover:bg-cream-50"
                  }`}
                >
                  {s}×
                </button>
              ))}
            </div>
          </div>
          {/* timeline scrubber */}
          <div className="mt-3">
            <input
              type="range"
              min={0}
              max={total}
              step={1}
              value={cursor}
              onChange={(e) => {
                setCursor(Number(e.target.value));
                setPlaying(false);
              }}
              className="w-full accent-accent-600"
            />
            <div className="flex justify-between text-[10px] uppercase tracking-widest text-ink-500">
              <span>开局</span>
              <span>
                第 {cursor} 手
                {lastMove?.spent_ms
                  ? ` · ${(lastMove.spent_ms / 1000).toFixed(1)}s`
                  : ""}
              </span>
              <span>终局</span>
            </div>
          </div>
          <div className="mt-2 text-[11px] text-ink-500">
            快捷键：空格 播放/暂停 · ←/→ 单步 · Home/End 头尾
          </div>
        </div>

        {cursor === total && result && (
          <div className="rounded-2xl border border-wood-100 bg-gradient-to-br from-cream-50 to-cream-100 p-5 shadow-card">
            <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent-600">
              Final
            </p>
            <h3 className="mt-1 font-display text-xl text-wood-800">
              {winner
                ? `${winner.display_name || winner.name} 获胜`
                : "和棋 / 结束"}
            </h3>
            <p className="mt-1 text-sm text-ink-600">{result.summary}</p>
          </div>
        )}
      </div>

      <aside className="space-y-4">
        <CommentaryStream
          moves={moves}
          players={players}
          highlightMoveNumber={highlightMoveNumber}
          onSelect={handleSelect}
        />
      </aside>
    </div>
  );
}
