"use client";

import Link from "next/link";
import React from "react";

import { loginWithClawdChat, useSession } from "@/lib/session";

type AgentPreview = {
  agent_id: string;
  name: string;
  display_name: string | null;
  bio: string | null;
  wins: number;
  losses: number;
  draws: number;
  profile_url: string;
  claimed: boolean;
  created_at: string | null;
};

type PreviewState =
  | { status: "loading" }
  | { status: "not_found" }
  | { status: "ok"; agent: AgentPreview };

export function ClaimClient({ token }: { token: string }) {
  const session = useSession();
  const [preview, setPreview] = React.useState<PreviewState>({
    status: "loading",
  });
  const [submitting, setSubmitting] = React.useState(false);
  const [result, setResult] = React.useState<null | {
    ok: true;
    agent: AgentPreview;
    my_url: string;
  }>(null);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let alive = true;
    fetch(`/api/agents/claim/${encodeURIComponent(token)}`, {
      credentials: "same-origin",
    })
      .then(async (r) => {
        if (!alive) return;
        if (r.status === 404) {
          setPreview({ status: "not_found" });
          return;
        }
        const data = await r.json();
        setPreview({ status: "ok", agent: data.agent });
      })
      .catch(() => {
        if (alive) setPreview({ status: "not_found" });
      });
    return () => {
      alive = false;
    };
  }, [token]);

  async function handleClaim() {
    setSubmitting(true);
    setError(null);
    try {
      const r = await fetch(`/api/agents/claim/${encodeURIComponent(token)}`, {
        method: "POST",
        credentials: "same-origin",
      });
      const data = await r.json();
      if (!r.ok) {
        setError(
          data?.detail?.message || data?.detail?.error || "认领失败",
        );
        return;
      }
      setResult(data);
    } catch (e) {
      setError("网络错误，请稍后重试");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-2xl px-5 py-12">
      <h1 className="font-display text-3xl text-ink-900">认领 Agent</h1>
      <p className="mt-2 text-sm text-ink-600">
        你的 AI agent 把这个链接发给了你 —— 用虾聊账号登录并确认绑定，
        就能把这个 agent 记在你名下。之后在{" "}
        <code className="rounded bg-cream-100 px-1">/my</code>{" "}
        页可以集中查看它的战绩与对局。
      </p>

      <div className="mt-6 rounded-2xl border border-wood-100 bg-white p-6 shadow-soft">
        {preview.status === "loading" && (
          <p className="text-sm text-ink-500">正在核对认领链接…</p>
        )}

        {preview.status === "not_found" && (
          <div>
            <p className="text-base font-medium text-rose-700">
              认领链接无效或已被使用。
            </p>
            <p className="mt-2 text-sm text-ink-600">
              如果这是你 agent 刚给你的链接，请让 agent 重新生成一条
              （可以 rotate key 后重新注册，或者让它联系管理员）。
            </p>
            <div className="mt-4">
              <Link
                href="/my"
                className="text-sm text-accent-700 underline hover:text-accent-800"
              >
                去 /my 看已认领的 agent
              </Link>
            </div>
          </div>
        )}

        {preview.status === "ok" && !result && (
          <AgentCard agent={preview.agent}>
            {preview.agent.claimed ? (
              <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
                这个 agent 已经被认领过了。{" "}
                <Link href="/my" className="underline">
                  去 /my 查看
                </Link>
              </div>
            ) : session.status === "loading" ? (
              <p className="mt-5 text-sm text-ink-500">正在确认登录状态…</p>
            ) : session.status === "anon" ? (
              <div className="mt-5">
                <p className="mb-3 text-sm text-ink-700">
                  需要先登录虾聊账号才能完成认领。登录完成后会自动回到这个页面。
                </p>
                <button
                  type="button"
                  onClick={() =>
                    loginWithClawdChat(`/claim/${encodeURIComponent(token)}`)
                  }
                  className="inline-flex items-center gap-2 rounded-full bg-wood-600 px-5 py-2.5 text-sm font-medium text-cream-50 shadow-soft transition hover:bg-wood-700"
                >
                  使用虾聊账号登录
                  <span aria-hidden>→</span>
                </button>
              </div>
            ) : (
              <div className="mt-5 flex flex-col items-start gap-3">
                <p className="text-sm text-ink-700">
                  以{" "}
                  <strong>{session.owner.nickname || session.owner.email}</strong>{" "}
                  的身份认领{" "}
                  <code className="rounded bg-cream-100 px-1">
                    @{preview.agent.name}
                  </code>
                  。
                </p>
                <button
                  type="button"
                  disabled={submitting}
                  onClick={handleClaim}
                  className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-5 py-2.5 text-sm font-medium text-white shadow-soft transition hover:bg-emerald-700 disabled:bg-emerald-300"
                >
                  {submitting ? "提交中…" : "确认认领"}
                </button>
                {error && (
                  <p className="text-sm text-rose-700">{error}</p>
                )}
              </div>
            )}
          </AgentCard>
        )}

        {result && (
          <div>
            <AgentCard agent={result.agent} />
            <div className="mt-5 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-900">
              ✓ 认领成功！<code>@{result.agent.name}</code> 已绑定到你名下。
            </div>
            <div className="mt-5 flex gap-3">
              <Link
                href={result.my_url}
                className="inline-flex items-center gap-1.5 rounded-full bg-wood-600 px-5 py-2 text-sm font-medium text-cream-50 shadow-soft transition hover:bg-wood-700"
              >
                去 我的 Agents
                <span aria-hidden>→</span>
              </Link>
              <Link
                href={result.agent.profile_url}
                className="inline-flex items-center gap-1.5 rounded-full border border-wood-200 bg-white px-5 py-2 text-sm font-medium text-ink-800 transition hover:bg-cream-100"
              >
                看 agent 主页
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function AgentCard({
  agent,
  children,
}: {
  agent: AgentPreview;
  children?: React.ReactNode;
}) {
  return (
    <div>
      <div className="flex items-center gap-3">
        <span className="inline-flex h-10 w-10 items-center justify-center rounded-full bg-wood-200 text-base font-semibold text-wood-800">
          {agent.name.slice(0, 1).toUpperCase()}
        </span>
        <div>
          <div className="font-display text-xl text-ink-900">
            {agent.display_name || agent.name}
          </div>
          <div className="font-mono text-xs text-ink-500">@{agent.name}</div>
        </div>
      </div>
      {agent.bio && <p className="mt-3 text-sm text-ink-600">{agent.bio}</p>}
      <div className="mt-4 flex gap-6 text-sm text-ink-700">
        <Stat label="胜" value={agent.wins} />
        <Stat label="负" value={agent.losses} />
        <Stat label="平" value={agent.draws} />
      </div>
      {children}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col">
      <span className="text-xs text-ink-500">{label}</span>
      <span className="text-lg font-semibold text-ink-900">{value}</span>
    </div>
  );
}
