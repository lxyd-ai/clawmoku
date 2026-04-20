from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLAWMOKU_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+aiosqlite:///./data/clawmoku.db"
    public_base_url: str = "https://gomoku.clawdchat.cn"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "https://gomoku.clawdchat.cn",
            "http://localhost:9002",
            "http://127.0.0.1:9002",
        ]
    )
    default_turn_timeout: int = 120  # seconds
    longpoll_max_wait: int = 30  # cap on ?wait=
    # Housekeeping: a `waiting` match (created but no opponent joined) is
    # auto-aborted after this many minutes. 0 disables the janitor.
    waiting_max_minutes: int = 30
    janitor_interval_sec: int = 60

    # ── ClawdChat SSO (owner login via external auth) ─────────────────
    # Upstream IdP root. `/api/v1/auth/external/authorize` (GET) hosts the
    # login UI, `/api/v1/auth/external/token` (POST) exchanges the one-time
    # code for a user payload. lang=zh → .cn domain.
    clawdchat_url: str = "https://clawdchat.cn"

    # Secret used to sign our own session JWT (owner cookie) and the short
    # CSRF-state cookie used during the OAuth round-trip. MUST be overridden
    # in production — a random `openssl rand -hex 32` is fine.
    jwt_secret: str = "clawmoku-dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    session_days: int = 7

    # Cookie flags. `session_cookie_secure=True` in prod (HTTPS); keep
    # False for plain http://localhost dev. SameSite=Lax is the right
    # default for "click link in email → login" flows (allows top-level
    # navigation to carry the cookie, blocks CSRF from 3rd-party pages).
    session_cookie_name: str = "clawmoku_session"
    oauth_state_cookie_name: str = "clawmoku_oauth_state"
    session_cookie_secure: bool = True
    session_cookie_samesite: str = "lax"  # lax|strict|none


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
