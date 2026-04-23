"use client";

import React from "react";

export type Stone = {
  x: number;
  y: number;
  color: "black" | "white";
  seq: number;
};

type Props = {
  size?: number;
  stones: Stone[];
  lastMove?: { x: number; y: number } | null;
  winningLine?: { x: number; y: number }[] | null;
  /**
   * Thumbnail mode for the lobby's "完赛" cards. Skips coordinate labels,
   * shrinks the wood frame, and uses thinner grid lines so a 200px-wide
   * SVG still reads cleanly. Star points stay visible but very faint.
   */
  compact?: boolean;
};

const FILES = "ABCDEFGHJKLMNOP"; // standard gomoku file labels (skip I)

export function Board({
  size = 15,
  stones,
  lastMove,
  winningLine,
  compact = false,
}: Props) {
  const cell = compact ? 12 : 34;
  const pad = compact ? 8 : 28;
  const w = pad * 2 + (size - 1) * cell;

  const winSet = new Set((winningLine || []).map((p) => `${p.x},${p.y}`));
  const starPoints =
    size === 15
      ? [
          [3, 3],
          [3, 11],
          [11, 3],
          [11, 11],
          [7, 7],
        ]
      : [];

  return (
    <div
      className={
        compact
          ? "rounded-[10px] border border-wood-600/20 bg-wood-texture p-1 shadow-soft ring-1 ring-wood-600/10"
          : "rounded-[22px] border border-wood-600/20 bg-wood-texture p-3 shadow-card ring-1 ring-wood-600/10"
      }
    >
      <svg
        viewBox={`0 0 ${w} ${w}`}
        className="block w-full"
        role="img"
        aria-label="Gomoku board"
      >
        <defs>
          <radialGradient id="stone-black" cx="30%" cy="30%" r="75%">
            <stop offset="0%" stopColor="#5a5a5a" />
            <stop offset="90%" stopColor="#0a0a0a" />
          </radialGradient>
          <radialGradient id="stone-white" cx="30%" cy="30%" r="85%">
            <stop offset="0%" stopColor="#ffffff" />
            <stop offset="100%" stopColor="#d1d1d1" />
          </radialGradient>
        </defs>

        {/* coordinates — skipped in compact thumbnail mode */}
        {!compact &&
          Array.from({ length: size }).map((_, i) => (
            <g key={`coord-${i}`} fill="#4a321a" opacity={0.55} fontSize={10} fontFamily="ui-monospace,monospace">
              <text x={pad + i * cell} y={pad - 12} textAnchor="middle">
                {FILES[i] ?? ""}
              </text>
              <text
                x={pad - 14}
                y={pad + i * cell + 3}
                textAnchor="middle"
              >
                {size - i}
              </text>
            </g>
          ))}

        {/* grid */}
        {Array.from({ length: size }).map((_, i) => (
          <g
            key={`grid-${i}`}
            stroke="#4a321a"
            strokeWidth={compact ? 0.4 : 0.9}
            opacity={compact ? 0.7 : 0.9}
          >
            <line
              x1={pad}
              y1={pad + i * cell}
              x2={pad + (size - 1) * cell}
              y2={pad + i * cell}
            />
            <line
              x1={pad + i * cell}
              y1={pad}
              x2={pad + i * cell}
              y2={pad + (size - 1) * cell}
            />
          </g>
        ))}

        {/* star points */}
        {starPoints.map(([x, y]) => (
          <circle
            key={`star-${x}-${y}`}
            cx={pad + x * cell}
            cy={pad + y * cell}
            r={compact ? 1.2 : 3.2}
            fill="#4a321a"
            opacity={compact ? 0.6 : 1}
          />
        ))}

        {/* winning line highlight */}
        {winningLine && winningLine.length >= 2 && (
          <line
            x1={pad + winningLine[0].x * cell}
            y1={pad + winningLine[0].y * cell}
            x2={pad + winningLine[winningLine.length - 1].x * cell}
            y2={pad + winningLine[winningLine.length - 1].y * cell}
            stroke="#dc2626"
            strokeWidth={compact ? 1.6 : 3}
            strokeLinecap="round"
            opacity={compact ? 0.85 : 0.7}
          />
        )}

        {/* stones */}
        {stones.map((s) => {
          const cx = pad + s.x * cell;
          const cy = pad + s.y * cell;
          const isWin = winSet.has(`${s.x},${s.y}`);
          const isLast = lastMove && lastMove.x === s.x && lastMove.y === s.y;
          return (
            <g key={`stone-${s.seq}`}>
              {/* shadow */}
              <ellipse
                cx={cx + 1}
                cy={cy + 2}
                rx={cell * 0.4}
                ry={cell * 0.34}
                fill="#000"
                opacity={0.18}
              />
              <circle
                cx={cx}
                cy={cy}
                r={cell * 0.42}
                fill={s.color === "black" ? "url(#stone-black)" : "url(#stone-white)"}
                stroke={
                  isWin
                    ? "#dc2626"
                    : s.color === "white"
                    ? "#a8a29e"
                    : "#000"
                }
                strokeWidth={isWin ? (compact ? 1 : 2) : compact ? 0.4 : 0.8}
              />
              {/* last-move dot omitted in compact mode to keep thumbnail clean */}
              {isLast && !compact && (
                <circle
                  cx={cx}
                  cy={cy}
                  r={cell * 0.14}
                  fill={s.color === "black" ? "#fafafa" : "#111"}
                />
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}
