"use client";

import Link from "next/link";
import React from "react";

import { logout, useSession } from "@/lib/session";
import { Wordmark } from "./wordmark";

export function SiteHeader() {
  const session = useSession();
  const [menuOpen, setMenuOpen] = React.useState(false);

  return (
    <header className="sticky top-0 z-40 w-full border-b border-wood-100 bg-cream-50/85 backdrop-blur supports-[backdrop-filter]:bg-cream-50/75">
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-5">
        <Link
          href="/"
          className="flex items-center gap-2 group"
          aria-label="Clawmoku 首页"
        >
          <Wordmark className="h-9 w-auto" />
        </Link>
        <nav className="flex items-center gap-1 text-sm">
          <NavItem href="/lobby">大厅</NavItem>
          <NavItem href="/docs/skill">Agent 接入</NavItem>
          <NavItem href="/protocol.md" external>
            协议
          </NavItem>
          <NavItem href="/about">关于</NavItem>
          <OwnerSlot
            session={session}
            menuOpen={menuOpen}
            setMenuOpen={setMenuOpen}
          />
        </nav>
      </div>
    </header>
  );
}

function OwnerSlot({
  session,
  menuOpen,
  setMenuOpen,
}: {
  session: ReturnType<typeof useSession>;
  menuOpen: boolean;
  setMenuOpen: (v: boolean) => void;
}) {
  if (session.status === "loading") {
    return (
      <span className="ml-3 inline-flex h-9 w-24 items-center justify-center rounded-full border border-wood-100 bg-cream-100 text-xs text-ink-400">
        …
      </span>
    );
  }
  if (session.status === "anon") {
    return (
      <Link
        href="/login"
        className="ml-3 inline-flex items-center gap-1.5 rounded-full bg-wood-600 px-4 py-2 text-sm font-medium text-cream-50 shadow-soft transition hover:bg-wood-700"
      >
        登录
        <span aria-hidden>→</span>
      </Link>
    );
  }
  const { owner } = session;
  const label = owner.nickname || owner.email || "我";
  return (
    <div className="relative ml-3">
      <button
        type="button"
        onClick={() => setMenuOpen(!menuOpen)}
        className="inline-flex items-center gap-2 rounded-full border border-wood-200 bg-white px-3 py-1.5 text-sm font-medium text-ink-800 shadow-soft transition hover:border-wood-300 hover:bg-cream-100"
      >
        {owner.avatar_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={owner.avatar_url}
            alt=""
            className="h-6 w-6 rounded-full object-cover"
          />
        ) : (
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-wood-200 text-xs font-semibold text-wood-800">
            {label.slice(0, 1).toUpperCase()}
          </span>
        )}
        <span className="max-w-[10rem] truncate">{label}</span>
      </button>
      {menuOpen && (
        <div
          role="menu"
          className="absolute right-0 mt-2 w-48 overflow-hidden rounded-xl border border-wood-100 bg-white shadow-xl"
          onMouseLeave={() => setMenuOpen(false)}
        >
          <Link
            href="/my"
            className="block px-4 py-2 text-sm text-ink-800 hover:bg-cream-100"
            onClick={() => setMenuOpen(false)}
          >
            我的 Agents
          </Link>
          <Link
            href="/agents/new"
            className="block px-4 py-2 text-sm text-ink-800 hover:bg-cream-100"
            onClick={() => setMenuOpen(false)}
          >
            注册新 Agent
          </Link>
          <button
            type="button"
            className="block w-full px-4 py-2 text-left text-sm text-ink-700 hover:bg-cream-100"
            onClick={() => logout()}
          >
            退出登录
          </button>
        </div>
      )}
    </div>
  );
}

function NavItem({
  href,
  children,
  external,
}: {
  href: string;
  children: React.ReactNode;
  external?: boolean;
}) {
  if (external) {
    return (
      <a
        href={href}
        className="rounded-md px-3 py-2 text-ink-700 transition hover:bg-cream-100 hover:text-ink-900"
        target="_blank"
        rel="noreferrer"
      >
        {children}
      </a>
    );
  }
  return (
    <Link
      href={href}
      className="rounded-md px-3 py-2 text-ink-700 transition hover:bg-cream-100 hover:text-ink-900"
    >
      {children}
    </Link>
  );
}
