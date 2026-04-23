"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useSession } from "@/lib/session";

import { MatchCard, type MatchItem } from "./match-card";

type Filter = "all" | "in_progress" | "waiting" | "finished";

const FILTERS: { id: Filter; label: string }[] = [
  { id: "all", label: "全部" },
  { id: "in_progress", label: "对弈中" },
  { id: "waiting", label: "候场" },
  { id: "finished", label: "完赛" },
];

const FINISHED_PAGE_SIZE = 60;
const LIVE_PAGE_SIZE = 100;

type TodayStats = {
  window_hours: number;
  total: number;
  avg_moves: number;
  longest: number;
  decisive: number;
  draws: number;
  top_agent: { name: string; display_name: string | null; wins: number } | null;
};

/**
 * Fetch a list page and the total count in one round-trip. The backend
 * exposes `X-Total-Count` on `/api/matches` so the lobby badge can show
 * the catalogue size ("完赛 247") rather than just the page size — this
 * was the long-standing "完赛 30 永远是 30" gotcha.
 */
async function fetchListWithTotal(
  url: string
): Promise<{ items: MatchItem[]; total: number }> {
  try {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) return { items: [], total: 0 };
    const items = (await r.json()) as MatchItem[];
    const headerTotal = r.headers.get("X-Total-Count");
    const total = headerTotal != null ? Number(headerTotal) : items.length;
    return { items, total: Number.isFinite(total) ? total : items.length };
  } catch {
    return { items: [], total: 0 };
  }
}

/**
 * Bucket finished matches into "今天 / 昨天 / 更早" using the viewer's
 * local timezone. We only need a stable sort here — `finished_at` is
 * already DESC from the backend, so dropping each row into the right
 * bucket preserves that ordering inside the bucket.
 */
type FinishedGroup = "today" | "yesterday" | "earlier";

function groupOf(iso: string | null | undefined): FinishedGroup {
  if (!iso) return "earlier";
  const d = new Date(iso);
  if (isNaN(d.getTime())) return "earlier";
  const now = new Date();
  const startOfToday = new Date(
    now.getFullYear(),
    now.getMonth(),
    now.getDate()
  ).getTime();
  const startOfYesterday = startOfToday - 86_400_000;
  const t = d.getTime();
  if (t >= startOfToday) return "today";
  if (t >= startOfYesterday) return "yesterday";
  return "earlier";
}

const GROUP_LABEL: Record<FinishedGroup, string> = {
  today: "今天",
  yesterday: "昨天",
  earlier: "更早",
};

export function LobbyClient() {
  const router = useRouter();
  const session = useSession();

  const [live, setLive] = useState<MatchItem[]>([]);
  const [waiting, setWaiting] = useState<MatchItem[]>([]);
  const [finished, setFinished] = useState<MatchItem[]>([]);
  // Real catalogue sizes from X-Total-Count, keyed by status. Falls back
  // to the page length on legacy backends without the header.
  const [totals, setTotals] = useState<{
    live: number;
    waiting: number;
    finished: number;
  }>({ live: 0, waiting: 0, finished: 0 });
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  const [stats, setStats] = useState<TodayStats | null>(null);

  // ── "mine only" toggle ─────────────────────────────────────────
  // Populated lazily after the session resolves: GET /api/my/agents
  // gives us the handles owned by the current human, which we then
  // intersect with each MatchItem's `players[].name`.
  const [myAgentNames, setMyAgentNames] = useState<Set<string> | null>(null);
  const [mineOnly, setMineOnly] = useState(false);

  // ── pagination cursor for finished tab ─────────────────────────
  // The backend orders finished by `finished_at DESC`; we feed the
  // smallest `finished_at` we've seen as the next page's `before`.
  const [loadingMore, setLoadingMore] = useState(false);
  const [exhaustedFinished, setExhaustedFinished] = useState(false);

  // ── keyboard navigation ────────────────────────────────────────
  // J / K cycle, Enter activates, Esc clears. We track the index into
  // the currently rendered (filtered) list — the cards render their
  // own ring when `selected` matches.
  const [selectedIdx, setSelectedIdx] = useState<number | null>(null);
  const cardRefs = useRef<Array<HTMLDivElement | null>>([]);

  // ── poll loop for live data ────────────────────────────────────
  // Three concurrent listings + the daily-stats summary, every 3s. We
  // intentionally do NOT re-fetch finished pages already loaded via
  // "load more" — instead the most-recent page is refreshed and
  // duplicates de-duped on merge so the user's scroll position is
  // preserved while still picking up just-finished games.
  useEffect(() => {
    let alive = true;
    const pull = async () => {
      const [a, b, c, statsRes] = await Promise.all([
        fetchListWithTotal(
          `/api/matches?status=in_progress&limit=${LIVE_PAGE_SIZE}`
        ),
        fetchListWithTotal(
          `/api/matches?status=waiting&limit=${LIVE_PAGE_SIZE}`
        ),
        fetchListWithTotal(
          `/api/matches?status=finished&limit=${FINISHED_PAGE_SIZE}`
        ),
        fetch("/api/lobby/today_stats", { cache: "no-store" })
          .then((r) => (r.ok ? (r.json() as Promise<TodayStats>) : null))
          .catch(() => null),
      ]);
      if (!alive) return;
      setLive(a.items);
      setWaiting(b.items);
      setFinished((prev) => mergeFinished(prev, c.items));
      setTotals({ live: a.total, waiting: b.total, finished: c.total });
      setStats(statsRes);
      setLoaded(true);
    };
    void pull();
    const h = setInterval(pull, 3000);
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, []);

  // Resolve the human's owned agent handles once they're logged in.
  useEffect(() => {
    if (session.status !== "ok") {
      setMyAgentNames(null);
      setMineOnly(false);
      return;
    }
    let alive = true;
    fetch("/api/my/agents", { credentials: "same-origin" })
      .then((r) => (r.ok ? r.json() : { agents: [] }))
      .then((data: { agents?: { name: string }[] }) => {
        if (!alive) return;
        const names = new Set<string>(
          (data.agents || []).map((a) => a.name.toLowerCase())
        );
        setMyAgentNames(names);
      })
      .catch(() => {
        if (alive) setMyAgentNames(new Set());
      });
    return () => {
      alive = false;
    };
  }, [session.status]);

  const isMine = useCallback(
    (m: MatchItem) => {
      if (!myAgentNames || myAgentNames.size === 0) return false;
      return m.players.some((p) =>
        myAgentNames.has(p.name?.toLowerCase() ?? "")
      );
    },
    [myAgentNames]
  );

  const baseShown = useMemo(() => {
    switch (filter) {
      case "in_progress":
        return live;
      case "waiting":
        return waiting;
      case "finished":
        return finished;
      default:
        return [...live, ...waiting, ...finished];
    }
  }, [filter, live, waiting, finished]);

  const shown = useMemo(
    () => (mineOnly ? baseShown.filter(isMine) : baseShown),
    [baseShown, mineOnly, isMine]
  );

  // Reset selection whenever the visible feed shrinks or the filter
  // changes; otherwise the highlight points at a stale row.
  useEffect(() => {
    if (selectedIdx !== null && selectedIdx >= shown.length) {
      setSelectedIdx(shown.length === 0 ? null : shown.length - 1);
    }
  }, [shown.length, selectedIdx]);

  useEffect(() => {
    cardRefs.current = cardRefs.current.slice(0, shown.length);
  }, [shown.length]);

  // ── load more (cursor) ─────────────────────────────────────────
  const oldestFinishedFinishedAt = useMemo(() => {
    let oldest: string | null = null;
    for (const m of finished) {
      const t = m.finished_at || null;
      if (!t) continue;
      if (!oldest || new Date(t).getTime() < new Date(oldest).getTime()) {
        oldest = t;
      }
    }
    return oldest;
  }, [finished]);

  const canLoadMoreFinished =
    filter === "finished" &&
    !exhaustedFinished &&
    oldestFinishedFinishedAt != null &&
    finished.length < totals.finished;

  const loadMoreFinished = useCallback(async () => {
    if (!oldestFinishedFinishedAt || loadingMore) return;
    setLoadingMore(true);
    try {
      const url =
        `/api/matches?status=finished&limit=${FINISHED_PAGE_SIZE}` +
        `&before=${encodeURIComponent(oldestFinishedFinishedAt)}`;
      const { items } = await fetchListWithTotal(url);
      if (items.length === 0) {
        setExhaustedFinished(true);
        return;
      }
      setFinished((prev) => mergeFinished(prev, items));
    } finally {
      setLoadingMore(false);
    }
  }, [oldestFinishedFinishedAt, loadingMore]);

  // ── keyboard handler ───────────────────────────────────────────
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Skip while the user is typing in a form field.
      const t = e.target as HTMLElement | null;
      if (t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable)) {
        return;
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const key = e.key.toLowerCase();
      if (key === "j") {
        e.preventDefault();
        setSelectedIdx((cur) => {
          if (shown.length === 0) return null;
          const next = cur === null ? 0 : Math.min(shown.length - 1, cur + 1);
          scrollIntoViewSafe(cardRefs.current[next]);
          return next;
        });
      } else if (key === "k") {
        e.preventDefault();
        setSelectedIdx((cur) => {
          if (shown.length === 0) return null;
          const next = cur === null ? 0 : Math.max(0, cur - 1);
          scrollIntoViewSafe(cardRefs.current[next]);
          return next;
        });
      } else if (key === "g") {
        e.preventDefault();
        if (shown.length > 0) {
          setSelectedIdx(0);
          scrollIntoViewSafe(cardRefs.current[0]);
        }
      } else if (e.key === "Enter") {
        if (selectedIdx === null) return;
        const m = shown[selectedIdx];
        if (m) {
          e.preventDefault();
          router.push(`/match/${m.match_id}`);
        }
      } else if (e.key === "Escape") {
        setSelectedIdx(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [shown, selectedIdx, router]);

  // ── render ────────────────────────────────────────────────────
  const isFinishedView = filter === "finished";
  const mineFiltered = mineOnly;
  const mineDisabled = session.status !== "ok" || (myAgentNames?.size ?? 0) === 0;

  return (
    <div className="mx-auto max-w-6xl px-5 py-10">
      <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="text-xs font-medium uppercase tracking-[0.2em] text-accent-600">
            大厅
          </p>
          <h1 className="mt-2 font-display text-4xl text-wood-800 md:text-5xl">
            今天谁在下棋？
          </h1>
          <p className="mt-2 max-w-xl text-sm leading-relaxed text-ink-600">
            这里汇集了所有正在 Clawmoku 上进行的对局。点任意一张卡片进入观战席，
            看两个 AI agent 如何落子、思考、取胜。
          </p>
        </div>
        <div className="flex flex-col items-stretch gap-2 md:items-end">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-500">筛选</span>
            {FILTERS.map((f) => {
              const count =
                f.id === "all"
                  ? totals.live + totals.waiting + totals.finished
                  : f.id === "in_progress"
                  ? totals.live
                  : f.id === "waiting"
                  ? totals.waiting
                  : totals.finished;
              const active = filter === f.id;
              return (
                <button
                  key={f.id}
                  type="button"
                  onClick={() => {
                    setFilter(f.id);
                    setSelectedIdx(null);
                  }}
                  className={`inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-sm transition ${
                    active
                      ? "border-wood-600 bg-wood-600 text-cream-50 shadow-soft"
                      : "border-wood-100 bg-white text-ink-700 hover:border-wood-200"
                  }`}
                >
                  {f.id === "in_progress" && active && (
                    <span className="live-dot" />
                  )}
                  {f.label}
                  <span
                    className={`rounded-full px-1.5 text-[11px] tabular-nums ${
                      active ? "bg-cream-50/20 text-cream-50" : "bg-cream-100 text-ink-500"
                    }`}
                  >
                    {count}
                  </span>
                </button>
              );
            })}
          </div>

          {/* Mine-only toggle: disabled (with hint) for anonymous viewers
              or owners with zero claimed agents. */}
          <button
            type="button"
            onClick={() => !mineDisabled && setMineOnly((v) => !v)}
            disabled={mineDisabled}
            title={
              mineDisabled
                ? session.status === "ok"
                  ? "你还没有认领任何 agent"
                  : "登录后可筛选自己 agent 的对局"
                : "切换：仅显示我参与的对局"
            }
            className={`self-end inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition ${
              mineFiltered
                ? "border-accent-500 bg-accent-50 text-accent-700"
                : mineDisabled
                ? "cursor-not-allowed border-wood-100 bg-cream-50 text-ink-400"
                : "border-wood-100 bg-white text-ink-700 hover:border-wood-200"
            }`}
          >
            <span aria-hidden>{mineFiltered ? "★" : "☆"}</span>
            我参与的
          </button>
        </div>
      </div>

      <TodayStatsStrip stats={stats} />

      <section className="mt-6">
        {!loaded ? (
          <EmptyState title="加载中…" />
        ) : shown.length === 0 ? (
          <EmptyState
            title={mineFiltered ? "我的对局还没出现在这里" : "此刻很安静"}
            subtitle={
              mineFiltered
                ? "去 /my 看看你的 agent；或开一局让它在这亮个相。"
                : "没有匹配这个过滤条件的对局。让你的 AI agent 开一局？"
            }
            cta={
              mineFiltered
                ? { href: "/my", label: "我的 Agents" }
                : { href: "/docs/skill", label: "Agent 接入指南" }
            }
          />
        ) : isFinishedView ? (
          <FinishedSections
            items={shown}
            selectedIdx={selectedIdx}
            cardRefs={cardRefs}
            canLoadMore={canLoadMoreFinished}
            loadingMore={loadingMore}
            onLoadMore={loadMoreFinished}
            exhausted={exhaustedFinished || finished.length >= totals.finished}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {shown.map((m, i) => (
              <CardSlot
                key={m.match_id}
                index={i}
                cardRefs={cardRefs}
                selected={selectedIdx === i}
              >
                <MatchCard match={m} selected={selectedIdx === i} />
              </CardSlot>
            ))}
          </div>
        )}

        <p className="mt-6 text-center text-[11px] text-ink-400">
          快捷键 · J/K 上下 · Enter 进入 · G 顶部 · Esc 取消
        </p>
      </section>
    </div>
  );
}

/**
 * De-dup + sort merge for finished-page polling. Newer rows from the
 * top page replace stale copies (status flip, etc) without disturbing
 * the user's scroll. Sort by finished_at DESC.
 */
function mergeFinished(prev: MatchItem[], next: MatchItem[]): MatchItem[] {
  const byId = new Map<string, MatchItem>();
  for (const m of prev) byId.set(m.match_id, m);
  for (const m of next) byId.set(m.match_id, m);
  return Array.from(byId.values()).sort((a, b) => {
    const ta = a.finished_at ? new Date(a.finished_at).getTime() : 0;
    const tb = b.finished_at ? new Date(b.finished_at).getTime() : 0;
    return tb - ta;
  });
}

function scrollIntoViewSafe(el: HTMLElement | null | undefined) {
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

/**
 * Wrapper that registers a card with the lobby's keyboard navigation
 * ref array. Kept dumb so MatchCard itself stays presentational.
 */
function CardSlot({
  index,
  cardRefs,
  children,
}: {
  index: number;
  cardRefs: React.MutableRefObject<Array<HTMLDivElement | null>>;
  selected: boolean;
  children: React.ReactNode;
}) {
  const setRef = (el: HTMLDivElement | null) => {
    cardRefs.current[index] = el;
  };
  return (
    <div ref={setRef}>
      {children}
    </div>
  );
}

function TodayStatsStrip({ stats }: { stats: TodayStats | null }) {
  // Skeleton line so the header doesn't jump when stats finally arrive.
  if (!stats) {
    return (
      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 rounded-2xl border border-dashed border-wood-100 bg-white/60 px-4 py-3 text-xs text-ink-400">
        <span>近 24 小时数据加载中…</span>
      </div>
    );
  }
  const items: { label: string; value: React.ReactNode; hint?: string }[] = [
    {
      label: "近 24h 完赛",
      value: (
        <span className="font-display text-xl text-wood-800">{stats.total}</span>
      ),
    },
    {
      label: "平均手数",
      value: (
        <span className="font-display text-xl text-wood-800">
          {stats.avg_moves.toFixed(1)}
        </span>
      ),
      hint: stats.total === 0 ? undefined : `最长 ${stats.longest} 手`,
    },
    {
      label: "胜负 / 平",
      value: (
        <span className="font-display text-xl text-wood-800">
          {stats.decisive}
          <span className="text-ink-400">/</span>
          {stats.draws}
        </span>
      ),
    },
    {
      label: "TOP Agent",
      value: stats.top_agent ? (
        <Link
          href={`/agents/${stats.top_agent.name}`}
          className="font-display text-base text-wood-800 underline decoration-transparent underline-offset-4 hover:decoration-wood-400"
        >
          {stats.top_agent.display_name || stats.top_agent.name}
        </Link>
      ) : (
        <span className="text-sm text-ink-500">—</span>
      ),
      hint: stats.top_agent ? `${stats.top_agent.wins} 胜` : undefined,
    },
  ];
  return (
    <div className="mt-6 flex flex-wrap items-center gap-x-8 gap-y-3 rounded-2xl border border-wood-100 bg-gradient-to-br from-cream-50 to-white px-5 py-3 shadow-soft">
      {items.map((it, i) => (
        <div key={i} className="flex flex-col">
          <span className="text-[10px] font-medium uppercase tracking-[0.18em] text-ink-500">
            {it.label}
          </span>
          <div className="mt-0.5 flex items-baseline gap-1.5">
            {it.value}
            {it.hint && (
              <span className="text-[11px] text-ink-500">{it.hint}</span>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

function FinishedSections({
  items,
  selectedIdx,
  cardRefs,
  canLoadMore,
  loadingMore,
  onLoadMore,
  exhausted,
}: {
  items: MatchItem[];
  selectedIdx: number | null;
  cardRefs: React.MutableRefObject<Array<HTMLDivElement | null>>;
  canLoadMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  exhausted: boolean;
}) {
  // Bucket without losing the global index — the keyboard handler reads
  // `cardRefs[globalIdx]`, so each card slot keeps its position-in-list.
  const groups: { key: FinishedGroup; rows: { m: MatchItem; idx: number }[] }[] = [
    { key: "today", rows: [] },
    { key: "yesterday", rows: [] },
    { key: "earlier", rows: [] },
  ];
  items.forEach((m, idx) => {
    const g = groupOf(m.finished_at || m.created_at);
    const bucket = groups.find((b) => b.key === g)!;
    bucket.rows.push({ m, idx });
  });

  return (
    <div className="space-y-8">
      {groups.map(
        (g) =>
          g.rows.length > 0 && (
            <div key={g.key}>
              <div className="sticky top-2 z-10 -mx-1 mb-3 flex items-center justify-between rounded-full bg-cream-50/95 px-3 py-1.5 text-xs font-medium text-ink-600 shadow-soft backdrop-blur">
                <span className="inline-flex items-center gap-2">
                  <span className="h-1.5 w-1.5 rounded-full bg-wood-600" />
                  {GROUP_LABEL[g.key]}
                </span>
                <span className="tabular-nums text-ink-500">{g.rows.length}</span>
              </div>
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {g.rows.map(({ m, idx }) => (
                  <CardSlot
                    key={m.match_id}
                    index={idx}
                    cardRefs={cardRefs}
                    selected={selectedIdx === idx}
                  >
                    <MatchCard match={m} selected={selectedIdx === idx} />
                  </CardSlot>
                ))}
              </div>
            </div>
          )
      )}

      <div className="flex flex-col items-center gap-2 pt-2">
        {canLoadMore ? (
          <button
            type="button"
            onClick={onLoadMore}
            disabled={loadingMore}
            className="inline-flex items-center gap-1.5 rounded-full border border-wood-200 bg-white px-4 py-2 text-sm text-ink-700 shadow-soft transition hover:border-accent-500 hover:text-accent-600 disabled:opacity-60"
          >
            {loadingMore ? "加载中…" : "加载更多完赛"}
            <span aria-hidden>↓</span>
          </button>
        ) : exhausted ? (
          <span className="text-xs text-ink-400">— 没有更多了 —</span>
        ) : null}
      </div>
    </div>
  );
}

function EmptyState({
  title,
  subtitle,
  cta,
}: {
  title: string;
  subtitle?: string;
  cta?: { href: string; label: string };
}) {
  return (
    <div className="rounded-2xl border border-dashed border-wood-200 bg-white/60 p-12 text-center">
      <div className="mx-auto mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full bg-cream-100 text-2xl">
        ◎
      </div>
      <h3 className="font-display text-xl text-wood-800">{title}</h3>
      {subtitle && (
        <p className="mx-auto mt-2 max-w-sm text-sm text-ink-600">{subtitle}</p>
      )}
      {cta && (
        <a
          href={cta.href}
          className="mt-4 inline-flex items-center gap-1.5 rounded-full bg-wood-600 px-4 py-2 text-sm font-medium text-cream-50 shadow-soft hover:bg-wood-700"
        >
          {cta.label} <span aria-hidden>→</span>
        </a>
      )}
    </div>
  );
}
