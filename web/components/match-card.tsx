"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React from "react";

export type MatchItem = {
  match_id: string;
  status: "waiting" | "in_progress" | "finished";
  players: {
    seat: number;
    name: string;
    display_name?: string | null;
    agent_id?: string | null;
    is_guest?: boolean;
    /**
     * ISO timestamp of the last observed poll / action from this seat.
     * Used to render the lobby "attendance light" — if the controller
     * stops long-polling, the lobby should show the seat as inactive so
     * spectators know there's nobody home.
     */
    last_seen_at?: string | null;
  }[];
  current_seat: number | null;
  created_at: string;
  move_count: number;
  waited_sec?: number;
  invite_url?: string;
};

/**
 * How fresh `last_seen_at` needs to be for a seat to read as "online".
 * Covers one 30s long-poll window plus a bit of network jitter. Keep in
 * sync with `Settings.attendance_online_sec` on the backend if you
 * change it.
 */
const ATTENDANCE_ONLINE_MS = 40_000;

type Attendance = "online" | "idle" | "unknown";

function attendance(lastSeen: string | null | undefined): Attendance {
  if (!lastSeen) return "unknown";
  const t = new Date(lastSeen).getTime();
  if (isNaN(t)) return "unknown";
  return Date.now() - t < ATTENDANCE_ONLINE_MS ? "online" : "idle";
}

type Props = {
  match: MatchItem;
  compact?: boolean;
};

/**
 * Deterministic colored avatar initials from a name.
 */
function avatarColor(name: string): string {
  const palette = [
    "#a16207",
    "#b45309",
    "#1d4ed8",
    "#065f46",
    "#7c2d12",
    "#6d28d9",
    "#be123c",
    "#0e7490",
  ];
  let h = 0;
  for (let i = 0; i < name.length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return palette[h % palette.length];
}

function initials(name: string): string {
  const clean = name.trim();
  if (!clean) return "?";
  const parts = clean.split(/[\s_-]+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return clean.slice(0, 2).toUpperCase();
}

function formatWaited(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ${sec % 60}s`;
  return `${Math.floor(sec / 3600)}h ${Math.floor((sec % 3600) / 60)}m`;
}

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "";
  const diff = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (diff < 60) return `${diff}s 前`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m 前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h 前`;
  return `${Math.floor(diff / 86400)}d 前`;
}

export function MatchCard({ match, compact }: Props) {
  const router = useRouter();
  const black = match.players.find((p) => p.seat === 0);
  const white = match.players.find((p) => p.seat === 1);
  const isWaiting = match.status === "waiting";
  const isLive = match.status === "in_progress";
  const isFinished = !isWaiting && !isLive;
  const statusLabel = isWaiting
    ? "等待对手"
    : isLive
    ? "对弈中"
    : "已结束";
  const href = `/match/${match.match_id}`;
  return (
    <div
      role="link"
      tabIndex={0}
      onClick={(e) => {
        if ((e.target as HTMLElement).closest("a[data-inner-link]")) return;
        router.push(href);
      }}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          router.push(href);
        }
      }}
      className="group block cursor-pointer rounded-2xl border border-wood-100 bg-white p-4 shadow-soft transition hover:-translate-y-0.5 hover:border-wood-200 hover:shadow-card focus:outline-none focus:ring-2 focus:ring-accent-500/40"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs">
          {isLive ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
              <span className="live-dot" />
              LIVE
            </span>
          ) : isWaiting ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-700">
              候场
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-ink-600/10 px-2 py-0.5 font-medium text-ink-600">
              完赛
            </span>
          )}
          <span className="font-mono text-ink-500">#{match.match_id}</span>
        </div>
        <span className="text-xs text-ink-500">{timeAgo(match.created_at)}</span>
      </div>

      <div className={`mt-3 grid ${compact ? "gap-2" : "gap-3"}`}>
        <PlayerRow
          side="black"
          player={black}
          isTurn={isLive && match.current_seat === 0}
          showAttendance={!isFinished}
        />
        <PlayerRow
          side="white"
          player={white}
          isTurn={isLive && match.current_seat === 1}
          showAttendance={!isFinished}
        />
      </div>

      <div className="mt-4 flex items-center justify-between text-xs text-ink-500">
        <span>
          {isWaiting && typeof match.waited_sec === "number"
            ? `已等 ${formatWaited(match.waited_sec)}`
            : `手数 ${match.move_count}`}
        </span>
        <span className="inline-flex items-center gap-1 text-ink-600 group-hover:text-accent-600">
          {statusLabel}
          <span aria-hidden>→</span>
        </span>
      </div>
    </div>
  );
}

function PlayerRow({
  side,
  player,
  isTurn,
  showAttendance,
}: {
  side: "black" | "white";
  player: MatchItem["players"][number] | undefined;
  isTurn: boolean;
  showAttendance: boolean;
}) {
  const display = player?.display_name || player?.name || "等待中…";
  const color = player ? avatarColor(display) : "#d6d3d1";
  const isGuest = !!player && player.is_guest === true;
  const stoneDot =
    side === "black" ? (
      <span className="stone-b" aria-hidden />
    ) : (
      <span className="stone-w" aria-hidden />
    );
  const status = player ? attendance(player.last_seen_at) : "unknown";
  return (
    <div
      className={`flex items-center gap-3 rounded-xl border px-3 py-2 ${
        isTurn
          ? "border-accent-500/40 bg-accent-50"
          : "border-cream-100 bg-cream-50"
      }`}
    >
      <div className="relative">
        <div
          className="flex h-8 w-8 items-center justify-center rounded-full text-xs font-semibold text-white"
          style={{ background: player ? color : "#a8a29e" }}
        >
          {player ? initials(display) : "?"}
        </div>
        {player && showAttendance && (
          <AttendanceDot status={status} isTurn={isTurn} />
        )}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5 text-sm font-medium text-ink-800">
          {stoneDot}
          {player && !isGuest ? (
            <Link
              href={`/agents/${player.name}`}
              data-inner-link
              className="truncate underline decoration-transparent underline-offset-2 transition hover:decoration-wood-400"
              onClick={(e) => e.stopPropagation()}
            >
              {display}
            </Link>
          ) : (
            <span className="truncate">{display}</span>
          )}
          {isGuest && (
            <span className="rounded bg-ink-600/10 px-1.5 py-px text-[10px] font-medium text-ink-600">
              游客
            </span>
          )}
        </div>
        <div className="text-[11px] text-ink-500">
          <span>{side === "black" ? "执黑先行" : "执白"}</span>
          {player && showAttendance && (
            <AttendanceLabel status={status} isTurn={isTurn} />
          )}
        </div>
      </div>
      {isTurn && (
        <span className="rounded-full bg-accent-600 px-2 py-0.5 text-[10px] font-medium uppercase tracking-wide text-white">
          on move
        </span>
      )}
    </div>
  );
}

/**
 * Small colored dot overlaid on the avatar. Green = agent is actively
 * long-polling the match; gray = hasn't called the API for a while;
 * yellow pulse = it's this agent's turn AND they're still online
 * (typical "thinking" state) — the dot joins the `on move` chip in
 * reassuring the spectator that somebody is, in fact, home.
 */
function AttendanceDot({
  status,
  isTurn,
}: {
  status: Attendance;
  isTurn: boolean;
}) {
  if (status === "unknown") return null;
  const color =
    status === "online"
      ? isTurn
        ? "#f59e0b" // amber — online & thinking
        : "#10b981" // emerald — online & idle
      : "#9ca3af"; // gray — gone
  const title =
    status === "online"
      ? isTurn
        ? "在线 · 思考中"
        : "在线 · 正在盯盘"
      : "离线 · 超过 40 秒未响应";
  return (
    <span
      title={title}
      aria-label={title}
      className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full ring-2 ring-white ${
        status === "online" && isTurn ? "animate-pulse" : ""
      }`}
      style={{ background: color }}
    />
  );
}

function AttendanceLabel({
  status,
  isTurn,
}: {
  status: Attendance;
  isTurn: boolean;
}) {
  if (status === "unknown") return null;
  const label =
    status === "online" ? (isTurn ? "思考中" : "在线") : "离线";
  const color =
    status === "online"
      ? isTurn
        ? "text-amber-600"
        : "text-emerald-600"
      : "text-ink-500";
  return <span className={`ml-1.5 ${color}`}>· {label}</span>;
}
