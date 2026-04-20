"use client";

/**
 * Tiny client-side session hook.
 *
 * Reads `/api/auth/session` once on mount. Owner info comes from the
 * HttpOnly session cookie set by `/api/auth/callback`; JS can't read
 * the cookie directly, so we ask the backend.
 *
 * No global provider — each component that cares re-uses the same hook,
 * and the fetch is cheap (small JSON, no DB join beyond a single Owner
 * lookup). If it becomes a hot path we can hoist into a Context.
 */

import React from "react";

export type Owner = {
  owner_id: string;
  clawdchat_user_id: string;
  nickname: string | null;
  avatar_url: string | null;
  email: string | null;
};

export type SessionState =
  | { status: "loading" }
  | { status: "anon" }
  | { status: "ok"; owner: Owner };

export function useSession(): SessionState {
  const [state, setState] = React.useState<SessionState>({ status: "loading" });

  React.useEffect(() => {
    let alive = true;
    fetch("/api/auth/session", { credentials: "same-origin" })
      .then((r) => r.json())
      .then((data) => {
        if (!alive) return;
        if (data.logged_in && data.owner) {
          setState({ status: "ok", owner: data.owner });
        } else {
          setState({ status: "anon" });
        }
      })
      .catch(() => {
        if (alive) setState({ status: "anon" });
      });
    return () => {
      alive = false;
    };
  }, []);

  return state;
}

/** Kick off ClawdChat SSO. `redirect` is where we want to land post-login
 *  (must be an absolute path on this site — the backend rejects anything
 *  that doesn't start with "/"). Full page navigation, not fetch. */
export function loginWithClawdChat(redirect: string = "/my") {
  const r = encodeURIComponent(redirect);
  window.location.href = `/api/auth/login?redirect=${r}`;
}

export async function logout(): Promise<void> {
  await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
  // Force a re-render everywhere by navigating to home.
  window.location.href = "/";
}
