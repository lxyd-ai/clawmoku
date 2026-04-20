"use client";

import React, { useEffect, useRef } from "react";

export type MoveEntry = {
  seq: number;
  move_number: number;
  seat: number;
  color: "black" | "white";
  x: number;
  y: number;
  ts?: string;
  spent_ms?: number | null;
  comment?: string | null;
  analysis?: Record<string, any> | null;
};

type PlayerInfo = {
  seat: number;
  name: string;
  display_name?: string | null;
};

type Props = {
  moves: MoveEntry[];
  players: PlayerInfo[];
  /** Optional: highlight this move (used by replay mode). */
  highlightMoveNumber?: number | null;
  /** Optional: clicking a move fires this (replay mode). */
  onSelect?: (moveNumber: number) => void;
  /** Auto-scroll to the newest move (live mode). */
  autoScroll?: boolean;
};

const FILES = "ABCDEFGHJKLMNOP";

function coordLabel(x: number, y: number): string {
  const file = FILES[x] ?? String(x);
  const rank = 15 - y;
  return `${file}${rank}`;
}

function fmtSpent(ms: number | null | undefined): string | null {
  if (!ms || ms < 50) return null;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  const m = Math.floor(ms / 60_000);
  const s = Math.floor((ms % 60_000) / 1000);
  return `${m}m ${s}s`;
}

function EvalBar({ value }: { value: number }) {
  const v = Math.max(-1, Math.min(1, value));
  const pct = ((v + 1) / 2) * 100;
  const color =
    v > 0.15
      ? "bg-emerald-500"
      : v < -0.15
      ? "bg-red-500"
      : "bg-ink-400";
  return (
    <div className="flex items-center gap-1.5" title={`eval ${v.toFixed(2)}`}>
      <span className="text-[10px] uppercase tracking-wider text-ink-500">
        eval
      </span>
      <div className="h-1.5 w-16 overflow-hidden rounded-full bg-cream-100">
        <div className={`h-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="font-mono text-[10px] text-ink-600">
        {v >= 0 ? "+" : ""}
        {v.toFixed(2)}
      </span>
    </div>
  );
}

function analysisChips(analysis: Record<string, any> | null | undefined) {
  if (!analysis) return null;
  const chips: React.ReactNode[] = [];
  if (typeof analysis.eval === "number") {
    chips.push(<EvalBar key="eval" value={analysis.eval} />);
  }
  if (Array.isArray(analysis.threats) && analysis.threats.length) {
    for (const t of analysis.threats.slice(0, 3)) {
      chips.push(
        <span
          key={`t-${t}`}
          className="rounded-full bg-red-50 px-2 py-0.5 text-[10px] font-medium text-red-700"
        >
          {String(t)}
        </span>
      );
    }
  }
  if (Array.isArray(analysis.pv) && analysis.pv.length) {
    const pvStr = analysis.pv
      .slice(0, 4)
      .map((p: any) =>
        Array.isArray(p) && p.length >= 2 ? coordLabel(p[0], p[1]) : "?"
      )
      .join(" → ");
    chips.push(
      <span
        key="pv"
        className="rounded-full bg-ink-900/5 px-2 py-0.5 font-mono text-[10px] text-ink-700"
      >
        PV {pvStr}
      </span>
    );
  }
  if (chips.length === 0) return null;
  return <div className="mt-1.5 flex flex-wrap items-center gap-1.5">{chips}</div>;
}

export function CommentaryStream({
  moves,
  players,
  highlightMoveNumber,
  onSelect,
  autoScroll,
}: Props) {
  const nameBySeat = new Map(
    players.map((p) => [p.seat, p.display_name || p.name])
  );
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!autoScroll || !scrollerRef.current) return;
    scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [moves.length, autoScroll]);

  const withComment = moves.filter((m) => m.comment || m.analysis).length;

  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-wood-100 bg-white shadow-soft">
      <div className="flex items-center justify-between border-b border-cream-100 px-4 py-3">
        <h3 className="font-display text-sm uppercase tracking-widest text-ink-500">
          解说流 · 棋谱
        </h3>
        <span className="text-xs text-ink-500">
          {moves.length} 手 · 解说 {withComment}
        </span>
      </div>
      <div
        ref={scrollerRef}
        className="flex-1 overflow-y-auto px-2 py-2"
        style={{ maxHeight: 620 }}
      >
        {moves.length === 0 ? (
          <div className="px-3 py-10 text-center text-sm text-ink-500">
            尚未落子 · 等待第一手
          </div>
        ) : (
          <ol className="space-y-1.5">
            {moves.map((m) => {
              const name = nameBySeat.get(m.seat) || `seat ${m.seat}`;
              const spent = fmtSpent(m.spent_ms);
              const selected = highlightMoveNumber === m.move_number;
              const clickable = typeof onSelect === "function";
              return (
                <li
                  key={m.seq}
                  onClick={clickable ? () => onSelect!(m.move_number) : undefined}
                  className={`rounded-xl border px-3 py-2 text-sm transition ${
                    selected
                      ? "border-accent-500 bg-accent-50"
                      : "border-transparent hover:border-wood-100 hover:bg-cream-50"
                  } ${clickable ? "cursor-pointer" : ""}`}
                >
                  <div className="flex items-center gap-2">
                    <span className="w-7 text-right font-mono text-xs text-ink-500">
                      {m.move_number}.
                    </span>
                    <span
                      className={m.color === "black" ? "stone-b" : "stone-w"}
                      aria-hidden
                    />
                    <span className="flex-1 truncate font-medium text-ink-800">
                      {name}
                    </span>
                    <span className="rounded-md bg-cream-100 px-1.5 py-0.5 font-mono text-[11px] text-ink-700">
                      {coordLabel(m.x, m.y)}
                    </span>
                    {spent && (
                      <span className="rounded-md bg-ink-900/5 px-1.5 py-0.5 font-mono text-[10px] text-ink-600">
                        {spent}
                      </span>
                    )}
                  </div>
                  {m.comment && (
                    <p className="ml-9 mt-1 rounded-lg bg-cream-50 px-2.5 py-1.5 text-[13px] leading-snug text-ink-700">
                      {m.comment}
                    </p>
                  )}
                  {analysisChips(m.analysis) && (
                    <div className="ml-9">{analysisChips(m.analysis)}</div>
                  )}
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
