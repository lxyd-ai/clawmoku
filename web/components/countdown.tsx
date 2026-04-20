"use client";

import React, { useEffect, useState } from "react";

type Props = {
  deadlineTs: number | null | undefined;
  /** Format verbosely as "mm:ss"; otherwise just a label-friendly string. */
  compact?: boolean;
};

export function Countdown({ deadlineTs, compact }: Props) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const h = setInterval(() => setNow(Date.now() / 1000), 500);
    return () => clearInterval(h);
  }, []);
  if (!deadlineTs) {
    return <span className="font-mono text-ink-500">—</span>;
  }
  const left = Math.max(0, Math.round(deadlineTs - now));
  const mm = Math.floor(left / 60);
  const ss = (left % 60).toString().padStart(2, "0");
  const warn = left <= 15;
  const caution = left <= 30 && !warn;
  return (
    <span
      className={`font-mono tabular-nums ${
        warn
          ? "text-red-600"
          : caution
          ? "text-accent-600"
          : "text-ink-700"
      }`}
    >
      {compact ? `${mm}:${ss}` : `${mm}:${ss}`}
    </span>
  );
}
