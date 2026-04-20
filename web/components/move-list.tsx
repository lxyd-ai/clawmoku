"use client";

import React from "react";

import type { Stone } from "./board";

type PlayerInfo = {
  seat: number;
  name: string;
  display_name?: string | null;
};

type Props = {
  stones: Stone[];
  players: PlayerInfo[];
};

const FILES = "ABCDEFGHJKLMNOP";

export function MoveList({ stones, players }: Props) {
  const nameBySeat = new Map(
    players.map((p) => [p.seat, p.display_name || p.name])
  );
  const ordered = [...stones].sort((a, b) => a.seq - b.seq);
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-2xl border border-wood-100 bg-white shadow-soft">
      <div className="flex items-center justify-between border-b border-cream-100 px-4 py-3">
        <h3 className="font-display text-sm uppercase tracking-widest text-ink-500">
          棋谱
        </h3>
        <span className="text-xs text-ink-500">{ordered.length} 手</span>
      </div>
      <div className="max-h-[460px] flex-1 overflow-auto px-2 py-2">
        {ordered.length === 0 ? (
          <div className="px-3 py-10 text-center text-sm text-ink-500">
            尚未落子
          </div>
        ) : (
          <ol className="divide-y divide-cream-100">
            {ordered.map((s) => {
              const seat = s.color === "black" ? 0 : 1;
              const name = nameBySeat.get(seat) || `seat ${seat}`;
              const file = FILES[s.x] ?? s.x;
              const rank = 15 - s.y; // assumes 15×15 rendering
              return (
                <li
                  key={s.seq}
                  className="flex items-center gap-3 px-2 py-2 text-sm"
                >
                  <span className="w-7 text-right font-mono text-xs text-ink-500">
                    {s.seq}
                  </span>
                  <span
                    className={
                      s.color === "black" ? "stone-b" : "stone-w"
                    }
                    aria-hidden
                  />
                  <span className="flex-1 truncate text-ink-800">{name}</span>
                  <span className="rounded-md bg-cream-100 px-2 py-0.5 font-mono text-[11px] text-ink-600">
                    {file}
                    {rank}
                  </span>
                </li>
              );
            })}
          </ol>
        )}
      </div>
    </div>
  );
}
