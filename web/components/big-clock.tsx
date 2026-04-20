"use client";

import React, { useEffect, useState } from "react";

type Player = {
  seat: number;
  name: string;
  display_name?: string | null;
};

type Props = {
  players: Player[];
  /** 0 or 1, or null when the clocks should freeze (waiting / finished). */
  currentSeat: number | null;
  /** Epoch seconds (server-provided) for current player's turn deadline. */
  deadlineTs: number | null;
  /** Cumulative thinking time (ms) per seat, accumulated locally. */
  accumulatedMs: Record<number, number>;
  /** Total turn budget in seconds, used to compute the ring progress. */
  turnTimeout: number;
};

function fmtClock(leftSec: number) {
  const clamped = Math.max(0, Math.ceil(leftSec));
  const mm = Math.floor(clamped / 60)
    .toString()
    .padStart(2, "0");
  const ss = (clamped % 60).toString().padStart(2, "0");
  return `${mm}:${ss}`;
}

function fmtCumulative(ms: number) {
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}m ${rem}s`;
}

/** Large chess-clock style panel, showing both sides simultaneously. */
export function BigClock({
  players,
  currentSeat,
  deadlineTs,
  accumulatedMs,
  turnTimeout,
}: Props) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now() / 1000), 250);
    return () => clearInterval(h);
  }, []);

  const black = players.find((p) => p.seat === 0);
  const white = players.find((p) => p.seat === 1);

  return (
    <div className="grid grid-cols-2 gap-3 rounded-2xl border border-wood-100 bg-gradient-to-br from-white to-cream-50 p-3 shadow-soft">
      <ClockTile
        side="black"
        player={black}
        active={currentSeat === 0}
        deadlineTs={deadlineTs}
        now={now}
        accumulatedMs={accumulatedMs[0] ?? 0}
        turnTimeout={turnTimeout}
      />
      <ClockTile
        side="white"
        player={white}
        active={currentSeat === 1}
        deadlineTs={deadlineTs}
        now={now}
        accumulatedMs={accumulatedMs[1] ?? 0}
        turnTimeout={turnTimeout}
      />
    </div>
  );
}

function ClockTile({
  side,
  player,
  active,
  deadlineTs,
  now,
  accumulatedMs,
  turnTimeout,
}: {
  side: "black" | "white";
  player: Player | undefined;
  active: boolean;
  deadlineTs: number | null;
  now: number;
  accumulatedMs: number;
  turnTimeout: number;
}) {
  const name = player?.display_name || player?.name || "—";
  const leftSec = active && deadlineTs ? deadlineTs - now : turnTimeout;
  const ratio = Math.max(0, Math.min(1, leftSec / Math.max(1, turnTimeout)));
  const warn = active && leftSec <= 15;
  const caution = active && leftSec <= 30 && !warn;

  return (
    <div
      className={`relative overflow-hidden rounded-xl border p-3 transition ${
        active
          ? warn
            ? "border-red-500/60 bg-red-50 ring-2 ring-red-500/30"
            : caution
            ? "border-accent-500/60 bg-accent-50 ring-2 ring-accent-500/20"
            : "border-emerald-500/50 bg-white ring-2 ring-emerald-500/10"
          : "border-wood-100 bg-white/70"
      }`}
    >
      <div className="flex items-center justify-between text-[11px] uppercase tracking-widest text-ink-500">
        <span className="flex items-center gap-1.5">
          <span
            className={`inline-block h-2.5 w-2.5 rounded-full ${
              side === "black" ? "bg-ink-900" : "bg-white ring-1 ring-ink-300"
            }`}
            aria-hidden
          />
          {side === "black" ? "黑方" : "白方"}
        </span>
        {active && (
          <span
            className={`rounded-full px-1.5 py-0.5 text-[9px] font-bold ${
              warn
                ? "bg-red-600 text-white animate-pulse"
                : "bg-emerald-600 text-white"
            }`}
          >
            {warn ? "LOW!" : "思考中"}
          </span>
        )}
      </div>
      <div className="mt-1.5 truncate text-sm font-medium text-ink-800">{name}</div>
      <div
        className={`mt-1 font-display text-4xl tabular-nums tracking-tight ${
          warn ? "text-red-600" : caution ? "text-accent-600" : "text-ink-900"
        } ${active && warn ? "animate-pulse" : ""}`}
      >
        {fmtClock(leftSec)}
      </div>
      <div className="mt-1 flex items-center justify-between text-[11px] text-ink-500">
        <span>累计 {fmtCumulative(accumulatedMs)}</span>
        <span className="font-mono">{Math.round(ratio * 100)}%</span>
      </div>
      {/* progress bar */}
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-cream-100">
        <div
          className={`h-full transition-[width] duration-200 ${
            warn
              ? "bg-red-500"
              : caution
              ? "bg-accent-500"
              : active
              ? "bg-emerald-500"
              : "bg-ink-300"
          }`}
          style={{ width: `${ratio * 100}%` }}
        />
      </div>
    </div>
  );
}
