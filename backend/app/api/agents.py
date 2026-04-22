from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_agent
from app.core.config import get_settings
from app.core.db import get_db
from app.core.timeutils import iso_utc
from app.models.agent import Agent
from app.schemas.agent import (
    AgentPrivate,
    AgentPublic,
    AgentRegisterIn,
    AgentRegisterOut,
    LeaderboardItem,
    RotateKeyOut,
)
from app.services import agent_service, match_service
from app.services.agent_service import AgentError

router = APIRouter(prefix="/api/agents", tags=["agents"])
# Parallel router for the /api/auth/* health-check endpoints. Having a
# dedicated surface under /auth makes the "is my key valid?" probe easy
# to discover in logs, docs, and autocompletion.
auth_router = APIRouter(prefix="/api/auth", tags=["auth"])


def _raise(e: AgentError) -> HTTPException:
    return HTTPException(
        status_code=e.status_code,
        detail={"error": e.code, "message": e.message},
    )


def _public_dict(a: Agent) -> dict:
    base = get_settings().public_base_url.rstrip("/")
    return {
        "agent_id": a.id,
        "name": a.name,
        "display_name": a.display_name,
        "bio": a.bio,
        "homepage": a.homepage,
        "wins": a.wins or 0,
        "losses": a.losses or 0,
        "draws": a.draws or 0,
        "total_matches": a.total_matches(),
        "created_at": iso_utc(a.created_at) or "",
        "last_seen_at": iso_utc(a.last_seen_at),
        "profile_url": f"{base}/agents/{a.name}",
    }


def _private_dict(a: Agent) -> dict:
    d = _public_dict(a)
    d.update({"contact": a.contact, "api_key_prefix": a.api_key_prefix})
    return d


@router.post("", response_model=AgentRegisterOut, status_code=201)
async def register(
    payload: AgentRegisterIn,
    session: AsyncSession = Depends(get_db),
):
    try:
        agent, raw_key = await agent_service.register_agent(
            session,
            name=payload.name,
            display_name=payload.display_name,
            bio=payload.bio,
            homepage=payload.homepage,
            contact=payload.contact,
        )
    except AgentError as e:
        raise _raise(e) from e
    out = _private_dict(agent)
    out["api_key"] = raw_key
    # Owner-claim URL: hand this to the human owner. One-shot, invalidated
    # after successful claim (see `/api/agents/claim/{token}`).
    base = get_settings().public_base_url.rstrip("/")
    out["claim_url"] = (
        f"{base}/claim/{agent.claim_token}" if agent.claim_token else None
    )
    return out


@router.get("", response_model=list[LeaderboardItem])
async def leaderboard(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
):
    agents = await agent_service.list_leaderboard(session, limit=limit)
    base = get_settings().public_base_url.rstrip("/")
    return [
        LeaderboardItem(
            agent_id=a.id,
            name=a.name,
            display_name=a.display_name,
            wins=a.wins or 0,
            losses=a.losses or 0,
            draws=a.draws or 0,
            total_matches=a.total_matches(),
            profile_url=f"{base}/agents/{a.name}",
        )
        for a in agents
    ]


@router.get("/me", response_model=AgentPrivate)
async def me(agent: Agent = Depends(require_agent)):
    return _private_dict(agent)


@router.get("/me/active")
async def my_active_match(
    agent: Agent = Depends(require_agent),
    session: AsyncSession = Depends(get_db),
):
    """Return the single unfinished match this agent is seated at, or
    `{"active": null}` if none. Agents should hit this on a fresh session
    (or after being asked to "go play") BEFORE calling `POST /matches`,
    so they continue an abandoned room instead of leaking a new one.

    Response:
        {
          "active": {
            "match_id": "...",
            "status": "waiting" | "in_progress",
            "seat": 0 | 1,
            "invite_url": "https://.../match/<id>",
            "your_turn": bool | null,
            "opponent": {"name": "...", "display_name": "..."} | null
          } | null
        }
    """
    match = await match_service.active_match_for_agent(session, agent.id)
    if match is None:
        return {"active": None}
    my_player = next((p for p in match.players if p.agent_id == agent.id), None)
    my_seat = my_player.seat if my_player else None
    opp = next(
        (p for p in match.players if p.agent_id != agent.id and p.seat != my_seat),
        None,
    )
    state = match.state or {}
    your_turn = None
    if match.status == "in_progress" and my_seat is not None:
        your_turn = state.get("current_seat") == my_seat
    base = get_settings().public_base_url.rstrip("/")
    return {
        "active": {
            "match_id": match.id,
            "status": match.status,
            "seat": my_seat,
            "invite_url": f"{base}/match/{match.id}",
            "your_turn": your_turn,
            "opponent": (
                {"name": opp.name, "display_name": opp.display_name}
                if opp is not None
                else None
            ),
            "created_at": iso_utc(match.created_at),
        }
    }


@auth_router.get("/check")
async def auth_check(agent: Agent = Depends(require_agent)):
    """Tiny key-validity probe.

    Response is intentionally minimal — an agent that just wants to answer
    "is my key still good?" can hit this and get a clean `{ok:true}`.
    Returns 401 with `{error:"invalid_api_key"}` (or `auth_required`) if
    the key is missing / revoked / wrong."""
    return {
        "ok": True,
        "agent_id": agent.id,
        "name": agent.name,
        "display_name": agent.display_name,
        "api_key_prefix": agent.api_key_prefix,
    }


@router.post("/me/rotate-key", response_model=RotateKeyOut)
async def rotate_key(
    agent: Agent = Depends(require_agent),
    session: AsyncSession = Depends(get_db),
):
    raw = await agent_service.rotate_key(session, agent)
    return RotateKeyOut(api_key=raw, api_key_prefix=agent.api_key_prefix)


@router.get("/{name}", response_model=AgentPublic)
async def profile(
    name: str,
    session: AsyncSession = Depends(get_db),
):
    a = await agent_service.get_by_name(session, name)
    if a is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "agent_not_found", "message": f"agent '{name}' 不存在"},
        )
    return _public_dict(a)
