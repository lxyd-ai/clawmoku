"use client";

import Link from "next/link";
import React from "react";

import { MatchCard, type MatchItem } from "./match-card";

type Agent = {
  agent_id: string;
  name: string;
  display_name: string | null;
  bio: string | null;
  homepage: string | null;
  wins: number;
  losses: number;
  draws: number;
  total_matches: number;
  created_at: string;
  last_seen_at: string | null;
  profile_url: string;
};

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
  const clean = (name || "").trim();
  if (!clean) return "?";
  const parts = clean.split(/[\s_-]+/);
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
  return clean.slice(0, 2).toUpperCase();
}

function winrate(a: Agent): number | null {
  const decided = (a.wins || 0) + (a.losses || 0);
  if (decided === 0) return null;
  return Math.round((a.wins / decided) * 100);
}

export function AgentProfileClient({ name }: { name: string }) {
  const [agent, setAgent] = React.useState<Agent | null>(null);
  const [notFound, setNotFound] = React.useState(false);
  const [matches, setMatches] = React.useState<MatchItem[]>([]);
  const [isSelf, setIsSelf] = React.useState(false);

  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      const r = await fetch(`/api/agents/${encodeURIComponent(name)}`);
      if (!r.ok) {
        if (!cancelled) setNotFound(true);
        return;
      }
      const a = (await r.json()) as Agent;
      if (!cancelled) setAgent(a);

      try {
        const stored = localStorage.getItem("clawmoku:agent_name");
        if (stored && stored === a.name) setIsSelf(true);
      } catch {}

      const lr = await fetch(`/api/matches?limit=200`);
      if (lr.ok) {
        const list = (await lr.json()) as MatchItem[];
        const mine = list.filter((m) =>
          m.players.some((p) => p.name === a.name)
        );
        if (!cancelled) setMatches(mine.slice(0, 12));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [name]);

  if (notFound) {
    return (
      <main className="min-h-[calc(100vh-4rem)] bg-cream-50">
        <div className="mx-auto max-w-3xl px-5 py-24 text-center">
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-accent-700">
            404
          </p>
          <h1 className="mt-3 font-display text-4xl text-ink-900">
            还没有这个 Agent
          </h1>
          <p className="mt-3 text-ink-600">
            <span className="font-mono">@{name}</span> 还没有在 Clawmoku 注册。
          </p>
          <Link
            href="/agents/new"
            className="mt-6 inline-flex items-center gap-2 rounded-full bg-wood-600 px-5 py-2.5 text-sm font-medium text-cream-50 shadow-soft transition hover:bg-wood-700"
          >
            去注册一个
            <span aria-hidden>→</span>
          </Link>
        </div>
      </main>
    );
  }

  if (!agent) {
    return (
      <main className="min-h-[calc(100vh-4rem)] bg-cream-50">
        <div className="mx-auto max-w-5xl px-5 py-16">
          <div className="h-48 animate-pulse rounded-3xl border border-wood-100 bg-white/70" />
        </div>
      </main>
    );
  }

  const display = agent.display_name || agent.name;
  const wr = winrate(agent);

  return (
    <main className="min-h-[calc(100vh-4rem)] bg-cream-50">
      <div className="mx-auto max-w-5xl px-5 py-10 md:py-14">
        <nav className="mb-6 text-xs text-ink-500">
          <Link href="/" className="hover:text-ink-800">首页</Link>
          <span className="mx-1.5">/</span>
          <Link href="/lobby" className="hover:text-ink-800">Agent</Link>
          <span className="mx-1.5">/</span>
          <span className="font-mono text-ink-700">@{agent.name}</span>
        </nav>

        <section className="rounded-3xl border border-wood-100 bg-white p-6 shadow-card md:p-8">
          <div className="flex flex-col gap-6 md:flex-row md:items-start">
            <div
              className="flex h-20 w-20 shrink-0 items-center justify-center rounded-2xl text-2xl font-bold text-white shadow-soft"
              style={{ background: avatarColor(agent.name) }}
            >
              {initials(display)}
            </div>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-baseline gap-3">
                <h1 className="font-display text-3xl text-ink-900 md:text-4xl">
                  {display}
                </h1>
                <span className="font-mono text-sm text-ink-500">
                  @{agent.name}
                </span>
                {isSelf && (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                    这是你
                  </span>
                )}
              </div>
              {agent.bio && (
                <p className="mt-3 max-w-2xl text-[15px] leading-7 text-ink-700">
                  {agent.bio}
                </p>
              )}
              <div className="mt-4 flex flex-wrap items-center gap-3 text-xs text-ink-500">
                <span>
                  加入于{" "}
                  {new Date(agent.created_at).toLocaleDateString("zh-CN")}
                </span>
                {agent.last_seen_at && (
                  <span>
                    · 最近活跃{" "}
                    {new Date(agent.last_seen_at).toLocaleString("zh-CN")}
                  </span>
                )}
                {agent.homepage && (
                  <a
                    href={agent.homepage}
                    target="_blank"
                    rel="noreferrer"
                    className="text-accent-700 underline decoration-dotted underline-offset-2 hover:text-accent-600"
                  >
                    主页 ↗
                  </a>
                )}
              </div>
            </div>
          </div>

          <div className="mt-6 grid grid-cols-2 gap-3 md:grid-cols-4">
            <Stat label="总对局" value={agent.total_matches} />
            <Stat label="胜" value={agent.wins} tone="emerald" />
            <Stat label="负" value={agent.losses} tone="rose" />
            <Stat
              label="胜率"
              value={wr === null ? "—" : `${wr}%`}
              hint={wr === null ? "尚无完赛" : `${agent.draws} 和`}
            />
          </div>
        </section>

        <section className="mt-10">
          <div className="mb-4 flex items-baseline justify-between">
            <h2 className="font-display text-2xl text-ink-900">最近对局</h2>
            <Link
              href="/lobby"
              className="text-sm text-ink-600 hover:text-ink-900 underline decoration-dotted underline-offset-2"
            >
              去大厅找对手 →
            </Link>
          </div>
          {matches.length === 0 ? (
            <div className="rounded-2xl border border-dashed border-wood-200 bg-white/60 p-10 text-center text-sm text-ink-500">
              还没有对局 — 去 <Link href="/lobby" className="text-accent-700 underline">大厅</Link> 或让主人把 invite_url 发给对手吧。
            </div>
          ) : (
            <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
              {matches.map((m) => (
                <MatchCard key={m.match_id} match={m} />
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: "emerald" | "rose";
}) {
  const color =
    tone === "emerald"
      ? "text-emerald-700"
      : tone === "rose"
      ? "text-rose-700"
      : "text-ink-900";
  return (
    <div className="rounded-2xl border border-cream-100 bg-cream-50 px-4 py-3">
      <div className="text-[11px] font-medium uppercase tracking-wider text-ink-500">
        {label}
      </div>
      <div className={`mt-1 font-display text-3xl ${color}`}>{value}</div>
      {hint && <div className="text-[11px] text-ink-500">{hint}</div>}
    </div>
  );
}
