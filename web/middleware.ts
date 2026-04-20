import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

// Match the "Agent 接入指南" doc path only. Everything else is untouched.
export const config = {
  matcher: ["/docs/skill"],
};

// User agents that almost certainly want raw markdown, not an HTML page.
// Keep this conservative: real browsers won't match; agent fetchers / CLIs will.
const NON_BROWSER_UA = /\b(curl|wget|httpie|python-requests|python-httpx|aiohttp|node-fetch|undici|go-http-client|okhttp|java|ruby|rustreqwest|claude|gpt|openai|anthropic|agent|bot)\b/i;

/**
 * Content-negotiation for /docs/skill:
 *   - Browser (Accept: text/html...) → serve the Next.js page.
 *   - Agent / CLI (curl, python-requests, LLM fetchers, …) → rewrite to
 *     /skill.md which next.config.js already proxies to the backend as raw
 *     markdown.
 *
 * This lets humans share a single URL and still have the command
 *   curl -s https://gomoku.clawd.xin/docs/skill
 * behave exactly like the agent expects.
 */
export function middleware(req: NextRequest) {
  const ua = req.headers.get("user-agent") || "";
  const accept = req.headers.get("accept") || "";

  const prefersMarkdown =
    /text\/(plain|markdown)/i.test(accept) &&
    !/text\/html/i.test(accept); // some browsers send both
  const looksLikeAgent = NON_BROWSER_UA.test(ua);
  const explicitOptIn = req.nextUrl.searchParams.has("raw");

  if (prefersMarkdown || looksLikeAgent || explicitOptIn) {
    const url = req.nextUrl.clone();
    url.pathname = "/skill.md";
    url.search = ""; // drop ?raw etc.
    return NextResponse.rewrite(url);
  }

  return NextResponse.next();
}
