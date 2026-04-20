from __future__ import annotations

import os
import tempfile
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio


@pytest.fixture(scope="session", autouse=True)
def _configure_env():
    """Per-test-session isolated sqlite DB, short default turn_timeout."""
    tmp = tempfile.mkdtemp(prefix="clawmoku-test-")
    os.environ["CLAWMOKU_DATABASE_URL"] = (
        f"sqlite+aiosqlite:///{tmp}/test.db"
    )
    os.environ["CLAWMOKU_PUBLIC_BASE_URL"] = "http://test.local"
    os.environ["CLAWMOKU_DEFAULT_TURN_TIMEOUT"] = "4"
    os.environ["CLAWMOKU_LONGPOLL_MAX_WAIT"] = "30"
    # Cookie + JWT knobs — test harness runs over plain http://test, so
    # `secure=True` would silently suppress all Set-Cookie round-trips.
    os.environ["CLAWMOKU_SESSION_COOKIE_SECURE"] = "false"
    os.environ["CLAWMOKU_JWT_SECRET"] = "test-jwt-secret"
    os.environ["CLAWMOKU_CLAWDCHAT_URL"] = "https://clawdchat.cn"
    yield


@pytest_asyncio.fixture
async def app() -> AsyncIterator:
    # Import after env is set.
    from app.main import app as fastapi_app

    # Ensure DB initialised (lifespan won't fire with transport=ASGI unless we enter it).
    from app.core.db import init_db

    await init_db()
    yield fastapi_app


@pytest_asyncio.fixture
async def client(app):
    from httpx import ASGITransport, AsyncClient

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
