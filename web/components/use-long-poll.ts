"use client";

import { useEffect, useRef, useState } from "react";

export type MatchEvent = {
  seq: number;
  type: string;
  data: Record<string, unknown>;
  ts: string;
};

export type LongPollState = {
  events: MatchEvent[];
  since: number;
  status: string | null;
  error: string | null;
  connected: boolean;
};

export function useLongPoll(matchId: string | null | undefined, initialSince = 0): LongPollState {
  const [events, setEvents] = useState<MatchEvent[]>([]);
  const [since, setSince] = useState<number>(initialSince);
  const [status, setStatus] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [connected, setConnected] = useState(false);

  const cancelRef = useRef(false);
  const backoffRef = useRef(1000);

  useEffect(() => {
    if (!matchId) return;
    cancelRef.current = false;
    let sinceLocal = initialSince;
    backoffRef.current = 1000;

    const loop = async () => {
      while (!cancelRef.current) {
        try {
          const controller = new AbortController();
          const url = `/api/matches/${encodeURIComponent(
            matchId
          )}/events?since=${sinceLocal}&wait=25`;
          const resp = await fetch(url, {
            signal: controller.signal,
            cache: "no-store",
          });
          if (!resp.ok) {
            if (resp.status === 404) {
              setError("match_not_found");
              return;
            }
            throw new Error(`HTTP ${resp.status}`);
          }
          const body = (await resp.json()) as {
            events: MatchEvent[];
            next_since: number;
            status: string;
          };
          if (cancelRef.current) return;
          setConnected(true);
          setError(null);
          backoffRef.current = 1000;
          if (body.events.length > 0) {
            setEvents((prev) => [...prev, ...body.events]);
            sinceLocal = body.next_since;
            setSince(body.next_since);
          }
          setStatus(body.status);
          if (body.status === "finished") {
            return;
          }
          // If no events and still in progress → loop immediately, server already held up to 25s
          if (body.events.length === 0) {
            await new Promise((r) => setTimeout(r, 500));
          }
        } catch (err) {
          if (cancelRef.current) return;
          setConnected(false);
          const msg = err instanceof Error ? err.message : String(err);
          setError(msg);
          const backoff = backoffRef.current;
          await new Promise((r) => setTimeout(r, backoff));
          backoffRef.current = Math.min(backoff * 2, 15000);
        }
      }
    };

    void loop();
    return () => {
      cancelRef.current = true;
    };
  }, [matchId, initialSince]);

  return { events, since, status, error, connected };
}
