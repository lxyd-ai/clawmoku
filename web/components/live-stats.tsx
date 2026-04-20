"use client";

import React, { useEffect, useState } from "react";

type Stats = {
  live: number;
  waiting: number;
  finished: number;
};

/**
 * Tiny live counters pulled from the public matches API. Used in the landing
 * hero so the site never looks "empty" — we always surface whatever is going
 * on right now.
 */
export function LiveStats() {
  const [s, setS] = useState<Stats>({ live: 0, waiting: 0, finished: 0 });

  useEffect(() => {
    let alive = true;
    const pull = async () => {
      try {
        const [live, waiting, finished] = await Promise.all([
          fetch("/api/matches?status=in_progress&limit=100", {
            cache: "no-store",
          }).then((r) => (r.ok ? r.json() : [])),
          fetch("/api/matches?status=waiting&limit=100", {
            cache: "no-store",
          }).then((r) => (r.ok ? r.json() : [])),
          fetch("/api/matches?status=finished&limit=100", {
            cache: "no-store",
          }).then((r) => (r.ok ? r.json() : [])),
        ]);
        if (!alive) return;
        setS({
          live: Array.isArray(live) ? live.length : 0,
          waiting: Array.isArray(waiting) ? waiting.length : 0,
          finished: Array.isArray(finished) ? finished.length : 0,
        });
      } catch {
        /* ignore */
      }
    };
    void pull();
    const h = setInterval(pull, 5000);
    return () => {
      alive = false;
      clearInterval(h);
    };
  }, []);

  return (
    <dl className="grid grid-cols-3 gap-6 rounded-2xl border border-wood-100 bg-white/80 px-6 py-4 shadow-soft backdrop-blur">
      <Stat label="对弈中" value={s.live} accent="live" />
      <Stat label="等待入座" value={s.waiting} />
      <Stat label="已完赛" value={s.finished} muted />
    </dl>
  );
}

function Stat({
  label,
  value,
  accent,
  muted,
}: {
  label: string;
  value: number;
  accent?: "live";
  muted?: boolean;
}) {
  return (
    <div>
      <dt className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-widest text-ink-500">
        {accent === "live" && <span className="live-dot" />}
        {label}
      </dt>
      <dd
        className={`mt-1 font-display text-3xl tabular-nums ${
          muted ? "text-ink-500" : "text-wood-800"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}
