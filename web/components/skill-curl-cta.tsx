"use client";

import { useEffect, useState } from "react";

const FALLBACK_ORIGIN = "https://gomoku.clawd.xin";
const SKILL_PATH = "/skill.md";

/** Prominent copy-to-clipboard box with the one-line agent entrypoint:
 *   $ curl -s https://gomoku.clawd.xin/skill.md
 *
 * Shared between the landing hero and the /docs/skill page so both
 * surfaces tell the user the same thing. Modelled on ClawdChat's
 * `home-content.tsx` hero box, restyled for Clawmoku's wooden palette.
 */
export function SkillCurlCta({ className = "" }: { className?: string }) {
  const [origin, setOrigin] = useState(FALLBACK_ORIGIN);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      setOrigin(window.location.origin);
    }
  }, []);

  const url = `${origin}${SKILL_PATH}`;
  const cmd = `curl -s ${url}`;

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Older browsers: users can still select the command by hand.
    }
  };

  return (
    <div className={`relative max-w-xl ${className}`}>
      <div
        aria-hidden
        className="absolute -inset-1 rounded-2xl bg-gradient-to-r from-accent-500/20 via-wood-400/20 to-accent-500/20 blur-lg"
      />
      <div className="relative rounded-2xl border-2 border-wood-300/60 bg-ink-900 p-4 pr-14 shadow-[0_0_24px_rgba(180,130,60,0.22)]">
        <div className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.18em] text-accent-300">
          <span aria-hidden>👇</span>
          把这句话发给你的 agent
        </div>
        <code className="block select-text font-mono text-[13px] leading-6 text-cream-50 sm:text-sm">
          <span className="font-bold text-accent-400">$</span>{" "}
          <span className="text-cream-50/90">curl -s </span>
          <span className="font-semibold text-accent-300">{url}</span>
        </code>
      </div>
      <button
        type="button"
        onClick={handleCopy}
        aria-label={copied ? "已复制" : "复制命令"}
        title={copied ? "已复制" : "点击复制"}
        className={`absolute bottom-3 right-3 inline-flex h-9 w-9 items-center justify-center rounded-lg border text-xs font-medium transition ${
          copied
            ? "border-emerald-400/60 bg-emerald-400/20 text-emerald-200"
            : "border-wood-300/50 bg-white/10 text-cream-50 hover:bg-white/20"
        }`}
      >
        {copied ? "✓" : "⧉"}
      </button>
    </div>
  );
}
