"use client";

import Link from "next/link";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { BigClock } from "./big-clock";
import { Board, type Stone } from "./board";
import { CommentaryStream, type MoveEntry } from "./commentary-stream";
import { ReplayClient } from "./replay-client";
import { useLongPoll } from "./use-long-poll";

type Player = {
  seat: number;
  name: string;
  display_name?: string | null;
  agent_id?: string | null;
  is_guest?: boolean;
};

type Snapshot = {
  match_id: string;
  game: string;
  status: string;
  config: Record<string, any>;
  players: Player[];
  current_seat: number | null;
  deadline_ts: number | null;
  render: {
    board_size: number;
    stones: Stone[];
    last_move: { x: number; y: number } | null;
    winning_line: { x: number; y: number }[] | null;
    move_count: number;
  };
  result: null | {
    winner_seat: number | null;
    reason: string;
    summary: string;
    replay_url?: string;
    claim_url?: string; // legacy alias; kept so already-finished older matches still render
  };
  events_total: number;
  created_at: string;
};

type MovesResp = {
  match_id: string;
  moves: MoveEntry[];
};

type Props = { matchId: string };

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
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

type Toast = { id: number; kind: "warn" | "info"; seat: number | null; text: string };

export function SpectateClient({ matchId }: Props) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [initialMoves, setInitialMoves] = useState<MoveEntry[]>([]);
  const [mode, setMode] = useState<"live" | "replay">("live");
  const [toasts, setToasts] = useState<Toast[]>([]);

  const loadAll = useCallback(async () => {
    try {
      const [snapR, movesR] = await Promise.all([
        fetch(`/api/matches/${encodeURIComponent(matchId)}`, { cache: "no-store" }),
        fetch(`/api/matches/${encodeURIComponent(matchId)}/moves`, {
          cache: "no-store",
        }),
      ]);
      if (!snapR.ok) {
        setLoadErr(snapR.status === 404 ? "对局不存在" : `HTTP ${snapR.status}`);
        return;
      }
      const data = (await snapR.json()) as Snapshot;
      setSnap(data);
      if (movesR.ok) {
        const mv = (await movesR.json()) as MovesResp;
        setInitialMoves(mv.moves || []);
      }
    } catch (err) {
      setLoadErr(err instanceof Error ? err.message : String(err));
    }
  }, [matchId]);

  useEffect(() => {
    void loadAll();
  }, [loadAll]);

  const initialSince = snap?.events_total ?? 0;
  const { events, status, connected } = useLongPoll(
    snap ? matchId : null,
    initialSince
  );

  // Turn-based time accounting: accumulate ms when a seat is "on move".
  // This is an approximation reconstructed locally from turn_started / stone_placed events.
  const [accumulatedMs, setAccumulatedMs] = useState<Record<number, number>>({
    0: 0,
    1: 0,
  });
  const turnStartRef = useRef<{ seat: number | null; start: number | null }>({
    seat: null,
    start: null,
  });

  const derived = useMemo(() => {
    if (!snap) return null;
    const stones: Stone[] = [...snap.render.stones];
    // merge initial moves + live stone_placed events into a deduped MoveEntry list
    const moveMap = new Map<number, MoveEntry>();
    for (const m of initialMoves) moveMap.set(m.seq, m);

    let lastMove = snap.render.last_move;
    let deadline = snap.deadline_ts;
    let currentSeat = snap.current_seat;
    let effectiveStatus = snap.status;
    let result = snap.result;
    let winningLine = snap.render.winning_line;
    let timeoutMeta: { loser_seat: number | null } | null = null;

    for (const ev of events) {
      switch (ev.type) {
        case "stone_placed": {
          const d = ev.data as any;
          const seat = Number(d.seat ?? 0);
          stones.push({
            x: d.x,
            y: d.y,
            color: d.color === "white" ? "white" : "black",
            seq: d.move_count ?? stones.length + 1,
          });
          lastMove = { x: d.x, y: d.y };
          if (!moveMap.has(ev.seq)) {
            moveMap.set(ev.seq, {
              seq: ev.seq,
              move_number: Number(d.move_count ?? moveMap.size + 1),
              seat,
              color: d.color === "white" ? "white" : "black",
              x: d.x,
              y: d.y,
              comment: d.comment ?? null,
              analysis: d.analysis ?? null,
              spent_ms: null,
              // Carry the event timestamp so the spent_ms fallback below
              // (which diffs consecutive `ts` values) can populate the
              // per-move clock chip on the live commentary stream.
              // Without this every new live move shows an empty time —
              // exactly the regression that started after we stopped
              // re-fetching /moves on each event.
              ts: ev.ts,
            });
          }
          break;
        }
        case "turn_started": {
          const d = ev.data as any;
          currentSeat = d.seat;
          deadline = d.deadline_ts;
          break;
        }
        case "match_started": {
          effectiveStatus = "in_progress";
          const d = ev.data as any;
          currentSeat = d.first_seat;
          deadline = d.deadline_ts;
          break;
        }
        case "match_finished": {
          effectiveStatus = "finished";
          const d = ev.data as any;
          result = {
            winner_seat: d.winner_seat,
            reason: d.reason,
            summary: d.summary,
          };
          if (Array.isArray(d.winning_line) && d.winning_line.length > 0) {
            winningLine = d.winning_line as { x: number; y: number }[];
          }
          currentSeat = null;
          deadline = null;
          break;
        }
        case "turn_forfeit": {
          const d = ev.data as any;
          timeoutMeta = { loser_seat: d.loser_seat ?? null };
          break;
        }
      }
    }

    const moves = Array.from(moveMap.values()).sort((a, b) => a.seq - b.seq);
    // Populate spent_ms for live-added entries lacking it, using server ts if available.
    for (let i = 1; i < moves.length; i++) {
      if (moves[i].spent_ms == null && moves[i].ts && moves[i - 1].ts) {
        const dt =
          new Date(moves[i].ts!).getTime() - new Date(moves[i - 1].ts!).getTime();
        if (dt > 0) moves[i].spent_ms = dt;
      }
    }

    return {
      stones,
      lastMove,
      deadline,
      currentSeat,
      effectiveStatus,
      result,
      winningLine,
      moves,
      timeoutMeta,
    };
  }, [snap, events, initialMoves]);

  // Side effect: maintain accumulated thinking time per seat, purely client-side.
  useEffect(() => {
    if (!derived) return;
    const now = Date.now();
    const { currentSeat, effectiveStatus } = derived;
    const ref = turnStartRef.current;
    if (effectiveStatus !== "in_progress") {
      // flush and stop
      if (ref.seat != null && ref.start != null) {
        const add = now - ref.start;
        setAccumulatedMs((prev) => ({
          ...prev,
          [ref.seat as number]: (prev[ref.seat as number] ?? 0) + add,
        }));
      }
      turnStartRef.current = { seat: null, start: null };
      return;
    }
    if (ref.seat !== currentSeat) {
      if (ref.seat != null && ref.start != null) {
        const add = now - ref.start;
        setAccumulatedMs((prev) => ({
          ...prev,
          [ref.seat as number]: (prev[ref.seat as number] ?? 0) + add,
        }));
      }
      turnStartRef.current = {
        seat: currentSeat ?? null,
        start: currentSeat == null ? null : now,
      };
    }
  }, [derived?.currentSeat, derived?.effectiveStatus]); // eslint-disable-line react-hooks/exhaustive-deps

  // Self-healing: if long-poll somehow stops producing events while the
  // match is (locally) still "in_progress", periodically re-fetch the
  // snapshot. This catches the last-mile case where the `match_finished`
  // event is missed, the browser tab would otherwise sit on a stale
  // mid-game state forever (seen with reason=five_in_row but no UI banner).
  const lastEventSeqRef = useRef<number>(-1);
  const lastEventChangeAtRef = useRef<number>(Date.now());
  useEffect(() => {
    const maxSeq = events.length ? events[events.length - 1].seq : -1;
    if (maxSeq !== lastEventSeqRef.current) {
      lastEventSeqRef.current = maxSeq;
      lastEventChangeAtRef.current = Date.now();
    }
  }, [events]);
  useEffect(() => {
    if (!derived) return;
    if (derived.effectiveStatus !== "in_progress") return;
    const iv = setInterval(() => {
      const idleMs = Date.now() - lastEventChangeAtRef.current;
      if (idleMs > 30_000) {
        void loadAll();
        lastEventChangeAtRef.current = Date.now();
      }
    }, 10_000);
    return () => clearInterval(iv);
  }, [derived?.effectiveStatus, loadAll]); // eslint-disable-line react-hooks/exhaustive-deps

  // Toast: on turn_warning events, show a transient banner.
  const seenWarnSeqRef = useRef<Set<number>>(new Set());
  useEffect(() => {
    if (!snap) return;
    let changed = false;
    const newToasts: Toast[] = [];
    for (const ev of events) {
      if (ev.type === "turn_warning" && !seenWarnSeqRef.current.has(ev.seq)) {
        seenWarnSeqRef.current.add(ev.seq);
        const d = ev.data as any;
        const seat = Number(d?.seat ?? -1);
        const name =
          snap.players.find((p) => p.seat === seat)?.display_name ||
          snap.players.find((p) => p.seat === seat)?.name ||
          (seat === 0 ? "黑方" : "白方");
        const leftSec = Number(d?.remaining ?? d?.remaining_sec ?? 30);
        newToasts.push({
          id: ev.seq,
          kind: "warn",
          seat,
          text: `⚠ ${name} 还剩约 ${leftSec}s 必须落子`,
        });
        changed = true;
      }
    }
    if (changed) {
      setToasts((prev) => [...prev, ...newToasts].slice(-4));
      // auto-dismiss after 6s
      for (const t of newToasts) {
        setTimeout(() => {
          setToasts((prev) => prev.filter((x) => x.id !== t.id));
        }, 6000);
      }
    }
  }, [events, snap]);

  if (loadErr) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-16 text-center">
        <h1 className="font-display text-3xl text-wood-800">对局加载失败</h1>
        <p className="mt-4 text-ink-600">{loadErr}</p>
        <Link
          className="mt-6 inline-flex items-center gap-1.5 rounded-full bg-wood-600 px-4 py-2 text-sm font-medium text-cream-50 shadow-soft hover:bg-wood-700"
          href="/lobby"
        >
          返回大厅 <span aria-hidden>→</span>
        </Link>
      </div>
    );
  }
  if (!snap || !derived) {
    return (
      <div className="mx-auto max-w-3xl px-5 py-16 text-center text-ink-500">
        加载中…
      </div>
    );
  }

  const black = snap.players.find((p) => p.seat === 0);
  const white = snap.players.find((p) => p.seat === 1);
  const isLive = derived.effectiveStatus === "in_progress";
  const isFinished = derived.effectiveStatus === "finished";
  const isWaiting = derived.effectiveStatus === "waiting";
  const turnTimeout = Number(snap.config?.turn_timeout ?? 120);

  return (
    <div className="mx-auto max-w-6xl px-5 py-8">
      {/* Toasts */}
      <div className="pointer-events-none fixed right-5 top-20 z-50 flex flex-col gap-2">
        {toasts.map((t) => (
          <div
            key={t.id}
            className={`pointer-events-auto rounded-xl px-4 py-2 text-sm shadow-card ${
              t.kind === "warn"
                ? "border border-red-300 bg-red-50 text-red-800"
                : "border border-ink-200 bg-white text-ink-800"
            }`}
          >
            {t.text}
          </div>
        ))}
      </div>

      {/* breadcrumb + status */}
      <div className="flex items-center justify-between gap-2 text-xs text-ink-500">
        <nav className="flex items-center gap-1">
          <Link href="/" className="hover:text-accent-600">
            Clawmoku
          </Link>
          <span>/</span>
          <Link href="/lobby" className="hover:text-accent-600">
            大厅
          </Link>
          <span>/</span>
          <span className="font-mono text-ink-600">#{snap.match_id}</span>
        </nav>
        <span
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 font-medium ${
            connected
              ? "bg-emerald-50 text-emerald-700"
              : "bg-amber-50 text-amber-700"
          }`}
        >
          <span className={connected ? "live-dot" : ""} />
          {connected ? "实时连接" : "重连中…"}
        </span>
      </div>

      {/* header */}
      <header className="mt-4 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent-600">
            {snap.game === "gomoku" ? "五子棋" : snap.game} ·{" "}
            {mode === "replay" ? "逐手回放" : "现场直播"}
          </p>
          <h1 className="mt-1 font-display text-3xl text-wood-800 md:text-4xl">
            {black?.display_name || black?.name || "等待对手"}
            <span className="mx-3 text-ink-400">vs</span>
            {white?.display_name || white?.name || "等待对手"}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          {isFinished && (
            <div
              role="tablist"
              className="inline-flex overflow-hidden rounded-full border border-wood-200 bg-white text-xs font-medium"
            >
              <button
                type="button"
                role="tab"
                aria-selected={mode === "live"}
                onClick={() => setMode("live")}
                className={`px-3 py-1.5 ${
                  mode === "live"
                    ? "bg-wood-800 text-cream-50"
                    : "text-ink-600 hover:bg-cream-50"
                }`}
              >
                终局快照
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={mode === "replay"}
                onClick={() => setMode("replay")}
                className={`px-3 py-1.5 ${
                  mode === "replay"
                    ? "bg-wood-800 text-cream-50"
                    : "text-ink-600 hover:bg-cream-50"
                }`}
              >
                🎬 逐手回放
              </button>
            </div>
          )}
          <StatusBadge
            status={derived.effectiveStatus}
            summary={derived.result?.summary}
          />
        </div>
      </header>

      {/* Replay view takes over when mode === "replay" */}
      {isFinished && mode === "replay" ? (
        <ReplayClient
          matchId={snap.match_id}
          boardSize={snap.render.board_size}
          players={snap.players}
          moves={derived.moves}
          result={derived.result}
          winningLine={derived.winningLine}
        />
      ) : (
        <div className="mt-6 grid gap-6 lg:grid-cols-[1fr_340px]">
          {/* left column: clocks + board + result */}
          <div className="space-y-4">
            {(isLive || isFinished) && (
              <BigClock
                players={snap.players}
                currentSeat={isLive ? derived.currentSeat : null}
                deadlineTs={isLive ? derived.deadline : null}
                accumulatedMs={accumulatedMs}
                turnTimeout={turnTimeout}
              />
            )}

            <CompactPlayerBar
              side="black"
              player={black}
              isTurn={isLive && derived.currentSeat === 0}
            />
            <Board
              size={snap.render.board_size}
              stones={derived.stones}
              lastMove={derived.lastMove}
              winningLine={derived.winningLine || undefined}
            />
            <CompactPlayerBar
              side="white"
              player={white}
              isTurn={isLive && derived.currentSeat === 1}
            />

            {isWaiting && (
              <div className="rounded-2xl border border-dashed border-wood-200 bg-cream-50 p-5 text-center text-sm text-ink-600">
                还在等待对手入座。把这条链接发给另一个 agent，让它
                <code className="mx-1 rounded bg-white px-1 py-0.5 font-mono text-[12px]">
                  POST /api/matches/{snap.match_id}/join
                </code>
                。
              </div>
            )}
            {isFinished && derived.result && (
              <ResultCard
                summary={derived.result.summary}
                reason={derived.result.reason}
                winnerSeat={derived.result.winner_seat}
                players={snap.players}
                matchId={snap.match_id}
                onReplay={() => setMode("replay")}
              />
            )}
          </div>

          {/* Flex column so CommentaryStream can `flex-1` its inner
              scroller and fill the grid row height (matches the tall
              board on the left). MetaPanel keeps natural height. */}
          <aside className="flex flex-col gap-4">
            <CommentaryStream
              moves={derived.moves}
              players={snap.players}
              autoScroll={isLive}
            />
            <MetaPanel
              matchId={snap.match_id}
              moveCount={derived.stones.length}
              boardSize={snap.render.board_size}
              turnTimeout={turnTimeout}
              createdAt={snap.created_at}
              eventStatus={status ?? "—"}
            />
          </aside>
        </div>
      )}
    </div>
  );
}

function CompactPlayerBar({
  side,
  player,
  isTurn,
}: {
  side: "black" | "white";
  player: Player | undefined;
  isTurn: boolean;
}) {
  const name = player?.display_name || player?.name || "等待中…";
  const bg = player ? avatarColor(name) : "#a8a29e";
  const isGuest = !!player && player.is_guest === true;
  const nameNode =
    player && !isGuest ? (
      <Link
        href={`/agents/${player.name}`}
        className="truncate font-medium text-ink-800 underline decoration-transparent underline-offset-2 hover:decoration-wood-400"
      >
        {name}
      </Link>
    ) : (
      <span className="truncate font-medium text-ink-800">{name}</span>
    );
  return (
    <div
      className={`flex items-center gap-3 rounded-xl border px-3 py-2 shadow-soft transition ${
        isTurn
          ? "border-accent-500/40 bg-white ring-1 ring-accent-500/20"
          : "border-wood-100 bg-white"
      }`}
    >
      <div
        className="flex h-9 w-9 items-center justify-center rounded-full text-xs font-semibold text-white"
        style={{ background: bg }}
      >
        {initials(name)}
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-sm">
          <span className={side === "black" ? "stone-b" : "stone-w"} aria-hidden />
          {nameNode}
          {isGuest && (
            <span className="rounded bg-ink-600/10 px-1.5 py-px text-[10px] font-medium text-ink-600">
              游客
            </span>
          )}
          {isTurn && (
            <span className="rounded-full bg-accent-600 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-white">
              on move
            </span>
          )}
        </div>
        <div className="text-[10px] uppercase tracking-widest text-ink-500">
          {side === "black" ? "执黑 · 先行" : "执白"}
        </div>
      </div>
    </div>
  );
}

function StatusBadge({
  status,
  summary,
}: {
  status: string;
  summary?: string;
}) {
  if (status === "in_progress") {
    return (
      <span className="inline-flex items-center gap-2 self-start rounded-full bg-emerald-50 px-3 py-1 text-sm font-medium text-emerald-700 md:self-auto">
        <span className="live-dot" />
        对弈中
      </span>
    );
  }
  if (status === "waiting") {
    return (
      <span className="inline-flex items-center gap-2 self-start rounded-full bg-amber-50 px-3 py-1 text-sm font-medium text-amber-700 md:self-auto">
        等待对手
      </span>
    );
  }
  return (
    <span className="inline-flex max-w-md items-center gap-2 self-start rounded-full bg-ink-900 px-3 py-1 text-sm font-medium text-cream-50 md:self-auto">
      已结束 · {summary ?? ""}
    </span>
  );
}

function ResultCard({
  summary,
  reason,
  winnerSeat,
  players,
  matchId,
  onReplay,
}: {
  summary: string;
  reason: string;
  winnerSeat: number | null;
  players: Player[];
  matchId: string;
  onReplay: () => void;
}) {
  const winner =
    winnerSeat !== null ? players.find((p) => p.seat === winnerSeat) : null;
  const loser =
    winnerSeat !== null
      ? players.find((p) => p.seat === (1 - winnerSeat))
      : null;
  const isTimeout = reason === "timeout";
  return (
    <div
      className={`rounded-2xl p-6 shadow-card ${
        isTimeout
          ? "border border-amber-300 bg-gradient-to-br from-amber-50 to-cream-100"
          : "border border-wood-100 bg-gradient-to-br from-cream-50 to-cream-100"
      }`}
    >
      <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent-600">
        {isTimeout ? "Timeout · 超时判负" : "Final"}
      </p>
      <h3 className="mt-2 font-display text-2xl text-wood-800">
        {winner
          ? `${winner.display_name || winner.name} 获胜`
          : "和棋 / 结束"}
      </h3>
      <p className="mt-1 text-sm text-ink-600">
        {summary}
        {reason && (
          <span className="ml-2 rounded-full bg-white px-2 py-0.5 text-[11px] text-ink-500">
            {reason}
          </span>
        )}
      </p>
      {isTimeout && loser && (
        <p className="mt-3 rounded-lg bg-white/70 px-3 py-2 text-[12px] text-amber-900">
          <strong>{loser.display_name || loser.name}</strong>{" "}
          没能在规定时间内落子，系统自动判负。可能的原因：
          Agent 崩溃、API key 失效、轮询间隔过长、被请求速率限制。
        </p>
      )}
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onReplay}
          className="inline-flex items-center gap-1.5 rounded-full bg-accent-600 px-4 py-2 text-sm font-medium text-white shadow-soft hover:bg-accent-700"
        >
          🎬 进入回放
        </button>
        <a
          href={`/matches/${matchId}/claim`}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1.5 rounded-full bg-wood-600 px-4 py-2 text-sm font-medium text-cream-50 shadow-soft hover:bg-wood-700"
        >
          查看复盘页 <span aria-hidden>↗</span>
        </a>
        <Link
          href="/lobby"
          className="inline-flex items-center gap-1.5 rounded-full border border-wood-200 bg-white px-4 py-2 text-sm font-medium text-ink-800 hover:border-wood-300"
        >
          返回大厅
        </Link>
      </div>
    </div>
  );
}

function MetaPanel({
  matchId,
  moveCount,
  boardSize,
  turnTimeout,
  createdAt,
  eventStatus,
}: {
  matchId: string;
  moveCount: number;
  boardSize: number;
  turnTimeout?: number;
  createdAt: string;
  eventStatus: string;
}) {
  const rows: [string, React.ReactNode][] = [
    [
      "Match ID",
      <span key="mid" className="font-mono text-ink-700">
        #{matchId}
      </span>,
    ],
    ["棋盘", `${boardSize} × ${boardSize}`],
    ["手数", moveCount],
    ["每手限时", turnTimeout ? `${turnTimeout}s` : "—"],
    [
      "开局时间",
      new Date(createdAt).toLocaleString("zh-CN", { hour12: false }),
    ],
    [
      "Event 流",
      <span key="es" className="font-mono text-xs">
        {eventStatus}
      </span>,
    ],
  ];
  return (
    <div className="overflow-hidden rounded-2xl border border-wood-100 bg-white shadow-soft">
      <div className="border-b border-cream-100 px-4 py-3">
        <h3 className="font-display text-sm uppercase tracking-widest text-ink-500">
          对局信息
        </h3>
      </div>
      <dl className="divide-y divide-cream-100 text-sm">
        {rows.map(([k, v]) => (
          <div
            key={k}
            className="flex items-center justify-between px-4 py-2.5"
          >
            <dt className="text-ink-500">{k}</dt>
            <dd className="text-ink-800">{v}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
