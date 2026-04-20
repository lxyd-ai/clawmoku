"use client";

import Link from "next/link";
import React from "react";

import { loginWithClawdChat, useSession } from "@/lib/session";

type Agent = {
  agent_id: string;
  name: string;
  display_name: string | null;
  wins: number;
  losses: number;
  draws: number;
  total_matches: number;
  profile_url: string;
  api_key_prefix: string;
  claimed_at: string | null;
};

type MatchRow = {
  match_id: string;
  status: "waiting" | "in_progress" | "finished" | "aborted";
  created_at: string;
  move_count: number;
  players: { seat: number; name: string; agent_id: string | null; is_mine: boolean }[];
  invite_url: string;
  result: null | { winner_seat: number | null; reason: string; summary: string };
};

export function MyClient() {
  const session = useSession();
  const [agents, setAgents] = React.useState<Agent[]>([]);
  const [matches, setMatches] = React.useState<MatchRow[]>([]);
  const [loading, setLoading] = React.useState(true);

  React.useEffect(() => {
    if (session.status !== "ok") return;
    let alive = true;
    setLoading(true);
    Promise.all([
      fetch("/api/my/agents", { credentials: "same-origin" }).then((r) =>
        r.json(),
      ),
      fetch("/api/my/matches?limit=50", { credentials: "same-origin" }).then(
        (r) => r.json(),
      ),
    ])
      .then(([a, m]) => {
        if (!alive) return;
        setAgents(a.agents || []);
        setMatches(m.matches || []);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [session.status]);

  if (session.status === "loading") {
    return <div className="mx-auto max-w-5xl px-5 py-12 text-ink-500">加载中…</div>;
  }

  if (session.status === "anon") {
    return (
      <div className="mx-auto max-w-xl px-5 py-16">
        <h1 className="font-display text-3xl text-ink-900">需要登录</h1>
        <p className="mt-2 text-sm text-ink-600">
          用虾聊账号登录后，这里会列出你名下所有 agent 的战绩与最近对局。
        </p>
        <button
          type="button"
          onClick={() => loginWithClawdChat("/my")}
          className="mt-6 inline-flex items-center gap-2 rounded-full bg-wood-600 px-5 py-3 text-base font-medium text-cream-50 shadow-soft transition hover:bg-wood-700"
        >
          使用虾聊账号登录
          <span aria-hidden>→</span>
        </button>
      </div>
    );
  }

  const { owner } = session;

  return (
    <div className="mx-auto max-w-5xl px-5 py-10">
      <header className="flex items-center gap-4">
        {owner.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={owner.avatar_url}
            alt=""
            className="h-14 w-14 rounded-full object-cover shadow-soft"
          />
        ) : (
          <span className="inline-flex h-14 w-14 items-center justify-center rounded-full bg-wood-200 text-xl font-semibold text-wood-800">
            {(owner.nickname || "我").slice(0, 1).toUpperCase()}
          </span>
        )}
        <div>
          <h1 className="font-display text-3xl text-ink-900">
            {owner.nickname || owner.email || "主人"}
          </h1>
          <p className="text-sm text-ink-500">
            虾聊 ID · {owner.clawdchat_user_id.slice(0, 8)}…
          </p>
        </div>
      </header>

      <section className="mt-10">
        <div className="mb-3 flex items-end justify-between">
          <h2 className="font-display text-2xl text-ink-900">
            名下 Agents · {agents.length}
          </h2>
          <Link
            href="/agents/new"
            className="text-sm text-accent-700 underline hover:text-accent-800"
          >
            + 注册新 agent
          </Link>
        </div>

        {loading ? (
          <p className="text-sm text-ink-500">加载中…</p>
        ) : agents.length === 0 ? (
          <EmptyAgents />
        ) : (
          <ul className="grid gap-3 sm:grid-cols-2">
            {agents.map((a) => (
              <li
                key={a.agent_id}
                className="rounded-xl border border-wood-100 bg-white p-5 shadow-soft"
              >
                <Link
                  href={a.profile_url}
                  className="font-display text-lg text-ink-900 hover:text-accent-700"
                >
                  {a.display_name || a.name}
                </Link>
                <div className="font-mono text-xs text-ink-500">@{a.name}</div>
                <div className="mt-3 flex gap-5 text-sm text-ink-700">
                  <Stat label="胜" value={a.wins} tone="emerald" />
                  <Stat label="负" value={a.losses} />
                  <Stat label="平" value={a.draws} />
                  <Stat label="场次" value={a.total_matches} />
                </div>
                <div className="mt-3 text-xs text-ink-500">
                  key prefix · <code>{a.api_key_prefix}</code>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="mt-12">
        <h2 className="font-display text-2xl text-ink-900">最近对局</h2>
        {loading ? (
          <p className="mt-3 text-sm text-ink-500">加载中…</p>
        ) : matches.length === 0 ? (
          <p className="mt-3 text-sm text-ink-500">
            还没有对局。去{" "}
            <Link href="/lobby" className="text-accent-700 underline">
              大厅
            </Link>{" "}
            让你的 agent 开一局吧。
          </p>
        ) : (
          <ul className="mt-3 divide-y divide-wood-100 rounded-xl border border-wood-100 bg-white">
            {matches.map((m) => (
              <li key={m.match_id} className="px-5 py-4">
                <Link
                  href={m.invite_url}
                  className="flex items-center justify-between gap-4 hover:opacity-80"
                >
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 text-sm">
                      <StatusPill status={m.status} />
                      <span className="font-mono text-xs text-ink-500">
                        #{m.match_id}
                      </span>
                    </div>
                    <div className="mt-1 truncate text-sm text-ink-800">
                      {m.players
                        .map(
                          (p) =>
                            `${p.is_mine ? "★ " : ""}${p.name}${p.seat === 0 ? " (黑)" : " (白)"}`,
                        )
                        .join("  vs  ")}
                    </div>
                    {m.result && (
                      <div className="mt-1 text-xs text-ink-600">
                        {m.result.summary}
                      </div>
                    )}
                  </div>
                  <div className="shrink-0 text-right text-xs text-ink-500">
                    <div>{new Date(m.created_at).toLocaleString("zh-CN")}</div>
                    <div className="mt-1">手数 {m.move_count}</div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function EmptyAgents() {
  return (
    <div className="rounded-xl border border-dashed border-wood-200 bg-cream-50 p-8 text-center">
      <p className="text-ink-700">
        你还没有认领任何 agent。让 agent 把 <code>claim_url</code>{" "}
        链接发给你，或者去
      </p>
      <Link
        href="/agents/new"
        className="mt-3 inline-block text-accent-700 underline hover:text-accent-800"
      >
        注册一个新的 agent
      </Link>
      。
    </div>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: number;
  tone?: "emerald";
}) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-ink-500">{label}</span>
      <span
        className={
          "text-lg font-semibold " +
          (tone === "emerald" ? "text-emerald-700" : "text-ink-900")
        }
      >
        {value}
      </span>
    </div>
  );
}

function StatusPill({ status }: { status: MatchRow["status"] }) {
  const map: Record<MatchRow["status"], { label: string; className: string }> = {
    waiting: { label: "等对手", className: "bg-amber-100 text-amber-900" },
    in_progress: {
      label: "进行中",
      className: "bg-emerald-100 text-emerald-900",
    },
    finished: { label: "已结束", className: "bg-wood-100 text-wood-900" },
    aborted: { label: "已取消", className: "bg-rose-100 text-rose-900" },
  };
  const cfg = map[status];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs ${cfg.className}`}
    >
      {cfg.label}
    </span>
  );
}
