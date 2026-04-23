"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React from "react";

import { Board, type Stone } from "./board";

export type MatchItem = {
  match_id: string;
  status: "waiting" | "in_progress" | "finished" | "aborted";
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
  // ── finished-only enrichments (populated by GET /api/matches when
  // the row is in a terminal state). Used by the post-game lobby card
  // to render a mini final-board thumbnail + winner badge in one shot.
  finished_at?: string | null;
  duration_sec?: number | null;
  result?: {
    winner_seat?: number | null;
    loser_seat?: number | null;
    reason?: string | null;
    summary?: string | null;
    aborted_by?: string | null;
  } | null;
  board_size?: number | null;
  stones?: Stone[] | null;
  last_move?: { x: number; y: number } | null;
  winning_line?: { x: number; y: number }[] | null;
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
  /**
   * Visually highlight the card as the current keyboard selection. The
   * lobby's J/K navigation toggles this on exactly one card at a time
   * so power users can scrub through a long list with the keyboard.
   */
  selected?: boolean;
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

/**
 * Compact human duration for finished matches: "12s" / "4:32" / "1:04:30".
 * Used in the post-game card so spectators can tell a 12-move blitz from a
 * 200-move slugfest at a glance.
 */
function formatDuration(sec: number): string {
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

/**
 * Map the backend's `result.reason` enum to a short, spectator-friendly
 * Chinese label rendered on the post-game pill. Falls back to the raw
 * reason for forward-compat with future game-end codes.
 */
function reasonLabel(reason: string | null | undefined): string {
  switch (reason) {
    case "five_in_row":
      return "五连胜";
    case "timeout":
      return "超时判负";
    case "resigned":
      return "认输";
    case "draw":
      return "平局";
    case "aborted":
      return "中途弃赛";
    default:
      return reason || "已结束";
  }
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

export function MatchCard({ match, compact, selected }: Props) {
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

  const onActivate = (e: React.MouseEvent | React.KeyboardEvent) => {
    if ((e.target as HTMLElement).closest("a[data-inner-link]")) return;
    if ((e.target as HTMLElement).closest("button[data-inner-action]")) return;
    router.push(href);
  };

  const selectedRing = selected
    ? "border-accent-500 ring-2 ring-accent-500/40"
    : "";

  // Finished cards get a dedicated layout: left = mini final-board
  // thumbnail (with winning line highlighted), right = vs / winner /
  // duration / replay CTA. Much faster scan than three near-identical
  // info rows, and the board itself is the most compelling preview.
  if (isFinished) {
    return (
      <FinishedCard
        match={match}
        black={black}
        white={white}
        href={href}
        onActivate={onActivate}
        selectedRing={selectedRing}
      />
    );
  }

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={onActivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate(e);
        }
      }}
      className={`group block cursor-pointer rounded-2xl border border-wood-100 bg-white p-4 shadow-soft transition hover:-translate-y-0.5 hover:border-wood-200 hover:shadow-card focus:outline-none focus:ring-2 focus:ring-accent-500/40 ${selectedRing}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 text-xs">
          {isLive ? (
            <span className="inline-flex items-center gap-1.5 rounded-full bg-emerald-50 px-2 py-0.5 font-medium text-emerald-700">
              <span className="live-dot" />
              LIVE
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 rounded-full bg-amber-50 px-2 py-0.5 font-medium text-amber-700">
              候场
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
          showAttendance
        />
        <PlayerRow
          side="white"
          player={white}
          isTurn={isLive && match.current_seat === 1}
          showAttendance
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

/**
 * Post-game card: mini board on the left, players + result + duration
 * on the right. Whole card is a link to the replay; the inner agent
 * handles still expose their own profile links via `data-inner-link`.
 */
function FinishedCard({
  match,
  black,
  white,
  href,
  onActivate,
  selectedRing,
}: {
  match: MatchItem;
  black: MatchItem["players"][number] | undefined;
  white: MatchItem["players"][number] | undefined;
  href: string;
  onActivate: (e: React.MouseEvent | React.KeyboardEvent) => void;
  selectedRing: string;
}) {
  const reason = match.result?.reason ?? null;
  const winnerSeat = match.result?.winner_seat;
  const isDraw = winnerSeat === null || winnerSeat === undefined;
  const isAborted = reason === "aborted" || match.status === "aborted";
  const blackWon = !isDraw && winnerSeat === 0;
  const whiteWon = !isDraw && winnerSeat === 1;

  const stones: Stone[] = (match.stones ?? []).map((s, i) => ({
    x: s.x,
    y: s.y,
    color: s.color,
    seq: typeof s.seq === "number" ? s.seq : i + 1,
  }));
  const boardSize = match.board_size ?? 15;

  // Result pill — color encodes winner side (black/white/draw/aborted).
  const pill = isAborted
    ? { bg: "bg-ink-600/10", fg: "text-ink-600", label: "中途弃赛" }
    : isDraw
    ? { bg: "bg-amber-50", fg: "text-amber-700", label: "平局" }
    : blackWon
    ? { bg: "bg-ink-900/90", fg: "text-cream-50", label: "⚫ 黑胜" }
    : { bg: "bg-cream-100", fg: "text-ink-800", label: "⚪ 白胜" };

  return (
    <div
      role="link"
      tabIndex={0}
      onClick={onActivate}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onActivate(e);
        }
      }}
      className={`group block cursor-pointer rounded-2xl border border-wood-100 bg-white p-4 shadow-soft transition hover:-translate-y-0.5 hover:border-wood-200 hover:shadow-card focus:outline-none focus:ring-2 focus:ring-accent-500/40 ${selectedRing}`}
    >
      {/* header */}
      <div className="flex items-center justify-between">
        <div className="flex min-w-0 items-center gap-2 text-xs">
          <span
            className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-medium ${pill.bg} ${pill.fg}`}
          >
            {pill.label}
          </span>
          {!isAborted && reason && (
            <span className="rounded-full bg-cream-100 px-2 py-0.5 text-[11px] font-medium text-ink-600">
              {reasonLabel(reason)}
            </span>
          )}
          <span className="truncate font-mono text-ink-500">#{match.match_id}</span>
        </div>
        <div className="flex items-center gap-2">
          <ShareButton match={match} />
          <span className="text-xs text-ink-500">
            {timeAgo(match.finished_at || match.created_at)}
          </span>
        </div>
      </div>

      <div className="mt-3 flex gap-3 sm:gap-4">
        {/* Mini final-board thumbnail. Width is responsive because the
            lobby grid jumps from 2-up (md) to 3-up (xl), shrinking each
            card to ~340px wide; a fixed 160px board left only ~140px
            for the right column and crushed the "查看回放" CTA into a
            vertical strip. We shrink the board on the 3-up grid so the
            right column stays readable. The Board SVG uses viewBox +
            w-full so its content scales automatically. */}
        <div className="w-[120px] flex-shrink-0 md:w-[160px] xl:w-[124px]">
          {/* Always render a real Board even for zero-move forfeits.
              The empty-grid thumbnail keeps the row visually consistent
              and itself carries information ("this agent never moved"),
              which a textual placeholder would obscure. */}
          <Board
            size={boardSize}
            stones={stones}
            lastMove={match.last_move ?? null}
            winningLine={match.winning_line ?? null}
            compact
          />
        </div>

        {/* right column: vs + winner highlight + meta */}
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          <FinishedPlayerRow
            side="black"
            player={black}
            won={blackWon}
            isDraw={isDraw}
            isAborted={isAborted}
          />
          <FinishedPlayerRow
            side="white"
            player={white}
            won={whiteWon}
            isDraw={isDraw}
            isAborted={isAborted}
          />

          {/* meta row: moves · duration */}
          <div className="mt-1 flex items-center gap-3 text-[11px] text-ink-500">
            <span className="inline-flex items-center gap-1">
              <span className="text-ink-700">{match.move_count}</span> 手
            </span>
            {typeof match.duration_sec === "number" && (
              <span className="inline-flex items-center gap-1">
                用时{" "}
                <span className="text-ink-700">
                  {formatDuration(match.duration_sec)}
                </span>
              </span>
            )}
          </div>

          <div className="mt-auto flex items-center justify-between gap-2 pt-1 text-xs">
            {/* `flex-1 min-w-0` + `truncate` on summary, and
                `flex-shrink-0` + `whitespace-nowrap` on the CTA so the
                right column never crushes the link into a vertical
                stack on the 3-up grid. */}
            <span className="min-w-0 flex-1 truncate text-ink-500">
              {match.result?.summary || ""}
            </span>
            <Link
              href={href}
              data-inner-link
              onClick={(e) => e.stopPropagation()}
              className="inline-flex flex-shrink-0 items-center gap-1 whitespace-nowrap rounded-full border border-wood-200 px-2.5 py-1 text-[11px] font-medium text-ink-700 transition hover:border-accent-500 hover:text-accent-600"
            >
              <span className="hidden sm:inline">查看</span>回放
              <span aria-hidden>→</span>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}

function FinishedPlayerRow({
  side,
  player,
  won,
  isDraw,
  isAborted,
}: {
  side: "black" | "white";
  player: MatchItem["players"][number] | undefined;
  won: boolean;
  isDraw: boolean;
  isAborted: boolean;
}) {
  const display = player?.display_name || player?.name || "—";
  const color = player ? avatarColor(display) : "#d6d3d1";
  const isGuest = !!player && player.is_guest === true;
  const stoneDot =
    side === "black" ? (
      <span className="stone-b" aria-hidden />
    ) : (
      <span className="stone-w" aria-hidden />
    );
  const dim = !won && !isDraw && !isAborted;
  return (
    <div
      className={`flex items-center gap-2 rounded-lg border px-2 py-1.5 transition ${
        won
          ? "border-amber-300 bg-amber-50/60 ring-1 ring-amber-300/40"
          : "border-cream-100 bg-cream-50"
      } ${dim ? "opacity-70" : ""}`}
    >
      <div className="relative">
        <div
          className="flex h-7 w-7 items-center justify-center rounded-full text-[11px] font-semibold text-white"
          style={{ background: player ? color : "#a8a29e" }}
        >
          {player ? initials(display) : "?"}
        </div>
        {won && (
          <span
            title="胜方"
            className="absolute -top-1.5 -right-1.5 text-xs leading-none"
            aria-label="winner"
          >
            👑
          </span>
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
          {side === "black" ? "执黑" : "执白"}
        </div>
      </div>
      {won && (
        <span className="rounded-full bg-amber-500 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
          win
        </span>
      )}
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

/**
 * Tiny "copy replay link" affordance for finished cards. Falls back to
 * the canonical /match/{id} path when the backend didn't include
 * `invite_url`. Stops click propagation + carries `data-inner-action`
 * so it doesn't trigger the surrounding card's navigation.
 */
function ShareButton({ match }: { match: MatchItem }) {
  const [copied, setCopied] = React.useState(false);

  const onClick = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    const fallback =
      typeof window !== "undefined"
        ? `${window.location.origin}/match/${match.match_id}`
        : `/match/${match.match_id}`;
    const url = match.invite_url || fallback;
    try {
      if (navigator?.clipboard?.writeText) {
        await navigator.clipboard.writeText(url);
      } else {
        // Legacy fallback: select-and-copy via a hidden textarea.
        const ta = document.createElement("textarea");
        ta.value = url;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        document.execCommand("copy");
        document.body.removeChild(ta);
      }
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      // Best-effort only — clipboard can be blocked by the browser; just
      // surface a tiny "失败" hint so the user knows to copy manually.
      setCopied(false);
    }
  };

  return (
    <button
      type="button"
      data-inner-action
      onClick={onClick}
      title={copied ? "已复制回放链接" : "复制回放链接"}
      aria-label="复制回放链接"
      className={`inline-flex h-6 items-center gap-1 rounded-full border px-2 text-[10px] font-medium transition ${
        copied
          ? "border-emerald-300 bg-emerald-50 text-emerald-700"
          : "border-wood-200 bg-white text-ink-600 hover:border-accent-500 hover:text-accent-600"
      }`}
    >
      <span aria-hidden>{copied ? "✓" : "🔗"}</span>
      {copied ? "已复制" : "分享"}
    </button>
  );
}
