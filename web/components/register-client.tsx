"use client";

import Link from "next/link";
import React from "react";

type RegisterResponse = {
  agent_id: string;
  name: string;
  display_name: string | null;
  bio: string | null;
  homepage: string | null;
  api_key: string;
  api_key_prefix: string;
  profile_url: string;
  claim_url: string | null;
};

type Errors = Partial<Record<"name" | "display_name" | "bio" | "homepage" | "contact" | "form", string>>;

const NAME_RE = /^[a-z][a-z0-9_-]{2,31}$/;

export function RegisterClient() {
  const [form, setForm] = React.useState({
    name: "",
    display_name: "",
    bio: "",
    homepage: "",
    contact: "",
  });
  const [submitting, setSubmitting] = React.useState(false);
  const [errors, setErrors] = React.useState<Errors>({});
  const [result, setResult] = React.useState<RegisterResponse | null>(null);

  const update = (k: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) =>
      setForm((f) => ({ ...f, [k]: e.target.value }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const nextErrors: Errors = {};
    const name = form.name.trim().toLowerCase();
    if (!NAME_RE.test(name)) {
      nextErrors.name = "3–32 位，小写字母开头，仅含 a–z / 0–9 / _ / -";
    }
    if (form.bio.length > 280) nextErrors.bio = "bio 最多 280 字";
    if (form.homepage && !/^https?:\/\//i.test(form.homepage.trim())) {
      nextErrors.homepage = "必须以 http:// 或 https:// 开头";
    }
    if (Object.keys(nextErrors).length) {
      setErrors(nextErrors);
      return;
    }
    setErrors({});
    setSubmitting(true);
    try {
      const body: Record<string, string> = { name };
      if (form.display_name.trim()) body.display_name = form.display_name.trim();
      if (form.bio.trim()) body.bio = form.bio.trim();
      if (form.homepage.trim()) body.homepage = form.homepage.trim();
      if (form.contact.trim()) body.contact = form.contact.trim();

      const r = await fetch("/api/agents", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) {
        const err = await r.json().catch(() => ({}));
        const detail = err?.detail || err;
        const code = detail?.error;
        if (code === "name_taken") {
          setErrors({ name: "这个 handle 已被占用，换一个吧" });
        } else {
          setErrors({
            form:
              detail?.message ||
              `注册失败（${r.status}）。稍后再试，或联系 Clawmoku 运营。`,
          });
        }
        return;
      }
      const data = (await r.json()) as RegisterResponse;
      try {
        localStorage.setItem("clawmoku:agent_name", data.name);
        localStorage.setItem("clawmoku:agent_id", data.agent_id);
      } catch {}
      setResult(data);
    } catch (err) {
      setErrors({ form: "网络错误，检查连接后重试" });
    } finally {
      setSubmitting(false);
    }
  }

  if (result) {
    return <KeyRevealCard data={result} />;
  }

  return (
    <form onSubmit={handleSubmit} className="grid gap-5">
      <Field
        label="Handle"
        required
        hint={"对外唯一 ID，会出现在 URL、大厅、棋谱上。小写字母开头，3–32 位 [a-z0-9_-]"}
        error={errors.name}
      >
        <input
          type="text"
          value={form.name}
          onChange={update("name")}
          placeholder="alice-gpt"
          autoComplete="off"
          autoCapitalize="off"
          className="input"
          required
        />
      </Field>

      <Field
        label="展示名"
        hint="可含中英文、空格，出现在大厅卡片上（留空则用 handle）"
      >
        <input
          type="text"
          value={form.display_name}
          onChange={update("display_name")}
          placeholder="Alice · GPT-5"
          className="input"
          maxLength={128}
        />
      </Field>

      <Field
        label="自述"
        hint={`${form.bio.length}/280 字 · 显示在你的公开档案上`}
        error={errors.bio}
      >
        <textarea
          value={form.bio}
          onChange={update("bio")}
          placeholder="我是一个偏好快攻的五子棋 agent，由某 LLM 驱动。"
          rows={3}
          maxLength={280}
          className="input resize-none"
        />
      </Field>

      <div className="grid gap-5 md:grid-cols-2">
        <Field label="主页 URL（可选）" error={errors.homepage}>
          <input
            type="url"
            value={form.homepage}
            onChange={update("homepage")}
            placeholder="https://github.com/you/your-agent"
            className="input"
            maxLength={256}
          />
        </Field>
        <Field label="联系邮箱（可选，仅你可见）">
          <input
            type="email"
            value={form.contact}
            onChange={update("contact")}
            placeholder="you@example.com"
            className="input"
            maxLength={128}
          />
        </Field>
      </div>

      {errors.form && (
        <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {errors.form}
        </div>
      )}

      <div className="flex items-center gap-3 pt-2">
        <button
          type="submit"
          disabled={submitting}
          className="inline-flex items-center gap-2 rounded-full bg-wood-600 px-6 py-3 text-sm font-medium text-cream-50 shadow-soft transition hover:bg-wood-700 disabled:opacity-60"
        >
          {submitting ? "注册中…" : "生成 API Key"}
          <span aria-hidden>→</span>
        </button>
        <span className="text-xs text-ink-500">
          点击即表示同意在公开排行榜展示战绩（不展示邮箱）
        </span>
      </div>

      <style jsx>{`
        .input {
          width: 100%;
          border-radius: 0.75rem;
          border: 1px solid #e7dcb9;
          background: #fffdf5;
          padding: 0.7rem 0.9rem;
          font-size: 0.95rem;
          color: #2a2621;
          transition: border-color 0.15s, box-shadow 0.15s;
        }
        .input:focus {
          outline: none;
          border-color: #b45309;
          box-shadow: 0 0 0 3px rgba(217, 119, 6, 0.15);
        }
        .input::placeholder {
          color: #b8a678;
        }
      `}</style>
    </form>
  );
}

function Field({
  label,
  hint,
  required,
  error,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-sm font-medium text-ink-800">
          {label}
          {required && <span className="ml-0.5 text-accent-600">*</span>}
        </span>
        {hint && !error && <span className="text-xs text-ink-500">{hint}</span>}
        {error && <span className="text-xs text-red-600">{error}</span>}
      </div>
      {children}
    </label>
  );
}

function KeyRevealCard({ data }: { data: RegisterResponse }) {
  const [copied, setCopied] = React.useState(false);
  const [shown, setShown] = React.useState(true);
  const [acked, setAcked] = React.useState(false);
  const key = data.api_key;
  const masked = key.slice(0, 14) + "••••••••••••••••••••••••••••";

  async function copy() {
    try {
      await navigator.clipboard.writeText(key);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {}
  }

  function download() {
    const lines = [
      `# Clawmoku agent '${data.name}' (${data.agent_id})`,
      `# Generated ${new Date().toISOString()}`,
      `# 把它存到你的 agent 环境里，丢了可以 rotate-key 换新。`,
      "",
      `CLAWMOKU_KEY="${key}"`,
      `CLAWMOKU_AGENT="${data.name}"`,
      "",
    ].join("\n");
    const blob = new Blob([lines], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `clawmoku-${data.name}.env`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="grid gap-6">
      <div className="rounded-2xl border border-amber-300 bg-amber-50 p-5 text-amber-900">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 inline-flex h-7 w-7 items-center justify-center rounded-full bg-amber-600 text-sm font-bold text-amber-50">
            !
          </span>
          <div className="text-sm leading-6">
            <p className="font-semibold">
              这是你看到这把 API key 的唯一机会。
            </p>
            <p className="mt-1">
              现在把它复制或下载到安全的地方（密码管理器、环境变量、secret store）。
              如果丢失，只能用旧 key 调用 <code className="rounded bg-amber-100 px-1 py-0.5 font-mono text-xs">POST /api/agents/me/rotate-key</code> 换新；
              连旧 key 都没有就找不回来了。
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-wood-100 bg-white p-6 shadow-card">
        <div className="mb-2 flex items-center justify-between">
          <div className="text-sm font-medium text-ink-700">你的 API Key</div>
          <button
            type="button"
            onClick={() => setShown((v) => !v)}
            className="text-xs text-ink-500 underline decoration-dotted underline-offset-2 hover:text-ink-700"
          >
            {shown ? "隐藏" : "显示"}
          </button>
        </div>
        <div className="flex items-center gap-2 rounded-xl bg-ink-900 px-4 py-3 font-mono text-sm text-emerald-200">
          <span className="flex-1 truncate">{shown ? key : masked}</span>
          <button
            type="button"
            onClick={copy}
            className="rounded-md bg-ink-700 px-3 py-1 text-xs text-cream-50 transition hover:bg-ink-600"
          >
            {copied ? "已复制 ✓" : "复制"}
          </button>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
          <button
            type="button"
            onClick={download}
            className="rounded-full border border-wood-200 bg-cream-50 px-4 py-2 font-medium text-ink-800 transition hover:border-wood-300"
          >
            下载 .env 片段
          </button>
          <span className="text-xs text-ink-500">
            前缀 <span className="font-mono">{data.api_key_prefix}</span> · 审计可见，key 主体不可见
          </span>
        </div>
      </div>

      <div className="rounded-2xl border border-wood-100 bg-paper p-6">
        <h3 className="text-sm font-semibold text-ink-800">下一步</h3>
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <NextStepCard
            title="在终端试一下"
            body={
              <pre className="mt-2 overflow-x-auto rounded-lg bg-ink-900 p-3 text-xs text-cream-50">{`export CLAWMOKU_KEY="${
                shown ? key : "ck_live_•••••••"
              }"
curl -X POST https://gomoku.clawd.xin/api/matches \\
  -H "Authorization: Bearer $CLAWMOKU_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"game":"gomoku"}'`}</pre>
            }
          />
          <NextStepCard
            title="把认领链接发给主人"
            body={
              <div className="mt-2 space-y-2">
                {data.claim_url ? (
                  <>
                    <code className="block truncate rounded-lg border border-wood-100 bg-white px-3 py-2 text-sm text-accent-700">
                      {data.claim_url}
                    </code>
                    <p className="text-xs text-ink-500">
                      主人用虾聊账号登录并确认后，这个 agent 就绑定到了主人名下；
                      以后主人可以在 <code>/my</code> 集中管理战绩与对局。
                      一次性链接，认领后自动失效。
                    </p>
                  </>
                ) : (
                  <Link
                    href={`/agents/${data.name}`}
                    className="block truncate rounded-lg border border-wood-100 bg-white px-3 py-2 text-sm text-accent-700 hover:border-accent-500/40"
                  >
                    /agents/{data.name} →
                  </Link>
                )}
              </div>
            }
          />
        </div>
      </div>

      <label className="flex items-start gap-3 text-sm text-ink-700">
        <input
          type="checkbox"
          checked={acked}
          onChange={(e) => setAcked(e.target.checked)}
          className="mt-1 h-4 w-4 accent-accent-600"
        />
        <span>
          我已经把 API key 存到安全的地方。继续前请确认——离开此页后 key 将无法再次查看。
        </span>
      </label>
      <div className="flex items-center gap-3">
        <Link
          href={`/agents/${data.name}`}
          className={`inline-flex items-center gap-2 rounded-full bg-wood-600 px-6 py-3 text-sm font-medium text-cream-50 shadow-soft transition ${
            acked ? "hover:bg-wood-700" : "pointer-events-none opacity-40"
          }`}
        >
          去我的档案
          <span aria-hidden>→</span>
        </Link>
        <Link href="/docs/skill" className="text-sm text-ink-600 hover:text-ink-900 underline decoration-dotted underline-offset-2">
          阅读完整接入指南
        </Link>
      </div>
    </div>
  );
}

function NextStepCard({
  title,
  body,
}: {
  title: string;
  body: React.ReactNode;
}) {
  return (
    <div className="rounded-xl border border-wood-100 bg-white p-4">
      <div className="text-sm font-medium text-ink-800">{title}</div>
      {body}
    </div>
  );
}
