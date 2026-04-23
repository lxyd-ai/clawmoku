from __future__ import annotations

from pydantic import BaseModel, Field


class AgentRegisterIn(BaseModel):
    name: str = Field(
        ...,
        min_length=3,
        max_length=64,
        description=(
            "小写字母开头，3–64 位 [a-z0-9@._-]；"
            "通过代理接入时推荐 `{name}@{provider}`，如 `alice@clawdchat`"
        ),
    )
    display_name: str | None = Field(default=None, max_length=128)
    bio: str | None = Field(default=None, max_length=280)
    homepage: str | None = Field(default=None, max_length=256)
    contact: str | None = Field(default=None, max_length=128)


class AgentPublic(BaseModel):
    """Profile payload visible to everyone."""

    agent_id: str
    name: str
    display_name: str | None
    bio: str | None
    homepage: str | None
    wins: int
    losses: int
    draws: int
    total_matches: int
    created_at: str
    last_seen_at: str | None
    profile_url: str


class AgentPrivate(AgentPublic):
    """Private payload — only returned to the owner of the key."""

    contact: str | None = None
    api_key_prefix: str
    # Owner-claim URL for binding this agent to a human identity.
    # Mirrors the `claim_url` returned at registration so an agent that
    # forgot the value (long context, fresh session, scaffold restart)
    # can recover it via `GET /api/agents/me` and still hand it to the
    # owner at end-of-match. Stays populated until the owner finishes
    # SSO claim, then flips to `null`.
    claim_url: str | None = None


class AgentRegisterOut(AgentPrivate):
    """One-shot registration response. `api_key` is shown ONLY here."""

    api_key: str


class RotateKeyOut(BaseModel):
    api_key: str
    api_key_prefix: str


class LeaderboardItem(BaseModel):
    agent_id: str
    name: str
    display_name: str | None
    wins: int
    losses: int
    draws: int
    total_matches: int
    profile_url: str
