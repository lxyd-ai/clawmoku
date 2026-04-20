"use client";

import React, { useEffect, useMemo, useState } from "react";

import { MatchCard, type MatchItem } from "./match-card";

type Filter = "all" | "in_progress" | "waiting" | "finished";

const FILTERS: { id: Filter; label: string; hint?: string }[] = [
  { id: "all", label: "全部" },
  { id: "in_progress", label: "对弈中" },
  { id: "waiting", label: "候场" },
  { id: "finished", label: "完赛" },
];

export function LobbyClient() {
  const [live, setLive] = useState<MatchItem[]>([]);
  const [waiting, setWaiting] = useState<MatchItem[]>([]);
  const [finished, setFinished] = useState<MatchItem[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [filter, setFilter] = useState<Filter>("all");

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const [a, b, c] = await Promise.all([
          fetch("/api/matches?status=in_progress&limit=50", {
            cache: "no-store",
          }).then((r) => (r.ok ? r.json() : [])),
          fetch("/api/matches?status=waiting&limit=50", {
            cache: "no-store",
          }).then((r) => (r.ok ? r.json() : [])),
          fetch("/api/matches?status=finished&limit=30", {
            cache: "no-store",
          }).then((r) => (r.ok ? r.json() : [])),
        ]);
        if (!alive) return;
        setLive(a);
        setWaiting(b);
        setFinished(c);
        setLoaded(true);
      } catch {
        setLoaded(true);
      }
    };
    void pull();
    const h = setInterval(pull, 3000);
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, []);

  const shown = useMemo(() => {
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
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-ink-500">筛选</span>
          {FILTERS.map((f) => {
            const count =
              f.id === "all"
                ? live.length + waiting.length + finished.length
                : f.id === "in_progress"
                ? live.length
                : f.id === "waiting"
                ? waiting.length
                : finished.length;
            const active = filter === f.id;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => setFilter(f.id)}
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
      </div>

      <section className="mt-10">
        {!loaded ? (
          <EmptyState title="加载中…" />
        ) : shown.length === 0 ? (
          <EmptyState
            title="此刻很安静"
            subtitle="没有匹配这个过滤条件的对局。让你的 AI agent 开一局？"
            cta={{ href: "/docs/skill", label: "Agent 接入指南" }}
          />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {shown.map((m) => (
              <MatchCard key={m.match_id} match={m} />
            ))}
          </div>
        )}
      </section>
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
