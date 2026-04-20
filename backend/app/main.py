from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse

from app.api import agent_claim, agents, auth, claim, matches, my
from app.core.config import get_settings
from app.core.db import init_db
from app.services import janitor

log = logging.getLogger("clawmoku")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    log.info("Clawmoku API ready — db initialised")
    janitor_task = asyncio.create_task(janitor.run(), name="clawmoku-janitor")
    try:
        yield
    finally:
        janitor_task.cancel()
        try:
            await janitor_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


app = FastAPI(
    title="Clawmoku API",
    version="0.1.0",
    description="Reference implementation of Board Game Protocol v1 (gomoku).",
    lifespan=lifespan,
)

settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(matches.router)
app.include_router(claim.router)
app.include_router(agents.router)
app.include_router(agents.auth_router)
app.include_router(agent_claim.router)
app.include_router(auth.router)
app.include_router(my.router)


@app.get("/healthz")
async def healthz():
    return {"ok": True, "service": "clawmoku"}


_DOCS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs")
)


def _read_docs_file(name: str) -> str:
    path = os.path.join(_DOCS_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


# The canonical host that docs in the repo are written against. Whenever
# a request comes from a different host (local dev, or a renamed prod
# domain), we rewrite the docs on the fly so copy-pasted curl/URL snippets
# "just work" from the caller's perspective.
_DOC_CANONICAL_HOST = "https://gomoku.clawdchat.cn"


def _is_loopback_host(host: str) -> bool:
    """Host is a loopback / "internal" address (no Forward header supplied)."""
    h = host.lower().split(":", 1)[0]
    return h in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def _localize_docs(text: str, request: Request) -> str:
    """Rewrite the canonical URL in skill/protocol docs so copy-pasted
    snippets "just work" for whichever host the caller used.

    Decision table (in order):

    1. `X-Forwarded-Host` present → trust it (nginx reverse-proxy case).
       The doc reflects the public domain the caller sees.
    2. Raw `Host` points at a public domain → use that.
    3. Raw `Host` is loopback AND we have a real `public_base_url` configured
       (i.e. we're a deployed instance being probed by an internal SSR
       fetch / health check) → rewrite to `public_base_url`, NOT to
       localhost. Otherwise `/docs/skill` served via Next.js would leak
       `127.0.0.1:9001` into a doc rendered under the production domain.
    4. Raw `Host` is loopback AND no public_base_url configured → local
       dev: rewrite to the loopback host (bump :9001 → :9002 so agents
       can `curl | python` the cred helper against the Next proxy)."""
    fwd_host = (request.headers.get("x-forwarded-host") or "").split(",")[0].strip()
    fwd_proto = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip()
    raw_host = (request.headers.get("host") or "").strip()

    public_base = get_settings().public_base_url.rstrip("/")
    public_base_is_real = bool(public_base) and "://127.0.0.1" not in public_base \
        and "://localhost" not in public_base

    if fwd_host:
        host = fwd_host
        scheme = fwd_proto or ("https" if request.url.scheme == "https" else "http")
        base = f"{scheme}://{host}"
    elif raw_host and not _is_loopback_host(raw_host):
        host = raw_host
        scheme = fwd_proto or ("https" if request.url.scheme == "https" else "http")
        base = f"{scheme}://{host}"
    elif public_base_is_real:
        # Internal loopback fetch on a deployed instance. Pretend the
        # caller asked for the public URL instead of leaking 127.0.0.1.
        base = public_base
    elif raw_host:
        # True local dev: caller really is on localhost.
        host = raw_host
        # Next.js dev proxy: API :9001, pages :9002. Bump port so URLs
        # aimed at the frontend (profile, match pages) resolve.
        if host.endswith(":9001"):
            host = host[: -len(":9001")] + ":9002"
        scheme = fwd_proto or ("https" if request.url.scheme == "https" else "http")
        base = f"{scheme}://{host}"
    else:
        return text

    replacements: list[tuple[str, str]] = []
    if base != _DOC_CANONICAL_HOST:
        replacements.append((_DOC_CANONICAL_HOST, base))
    if public_base and public_base != _DOC_CANONICAL_HOST and public_base != base:
        replacements.append((public_base, base))
    if not replacements:
        return text
    banner = (
        "<!-- clawmoku:doc-rewrite "
        + " ; ".join(f"{src} → {dst}" for src, dst in replacements)
        + " -->\n"
    )
    out = text
    for src, dst in replacements:
        out = out.replace(src, dst)
    return banner + out


@app.get("/skill.md", response_class=PlainTextResponse)
async def skill_md(request: Request):
    """The agent skill document, served raw so `curl https://.../skill.md` works."""
    try:
        text = _read_docs_file("gomoku-skill.md")
    except FileNotFoundError:
        return PlainTextResponse("# skill doc missing", status_code=404)
    return PlainTextResponse(_localize_docs(text, request))


@app.get("/protocol.md", response_class=PlainTextResponse)
async def protocol_md(request: Request):
    try:
        text = _read_docs_file("partner-spec/board-game-v1.md")
    except FileNotFoundError:
        return PlainTextResponse("# protocol doc missing", status_code=404)
    return PlainTextResponse(_localize_docs(text, request))


@app.get("/clawmoku-cred.py", response_class=PlainTextResponse)
async def cred_helper():
    """Tiny stdlib-only credential manager agents `curl | python3 -` on first use."""
    try:
        return _read_docs_file("scripts/clawmoku-cred.py")
    except FileNotFoundError:
        return PlainTextResponse("# helper missing", status_code=404)
