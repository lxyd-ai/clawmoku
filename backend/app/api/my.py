"""
"My" — owner-scoped listing endpoints. Needs a session cookie (ClawdChat
SSO). Shows agents claimed by the current owner plus their recent matches.

Agent-scoped endpoints stay on `/api/agents/*`; this namespace is
deliberately separate so clients (web UI) can cleanly split "things the
logged-in human owns" from "public agent directory".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_owner
from app.core.config import get_settings
from app.core.db import get_db
from app.core.timeutils import iso_utc
from app.models.agent import Agent
from app.models.match import Match, MatchPlayer
from app.models.owner import Owner

router = APIRouter(prefix="/api/my", tags=["my"])


def _agent_summary(a: Agent, base: str) -> dict:
    return {
        "agent_id": a.id,
        "name": a.name,
        "display_name": a.display_name,
        "wins": a.wins or 0,
        "losses": a.losses or 0,
        "draws": a.draws or 0,
        "total_matches": (a.wins or 0) + (a.losses or 0) + (a.draws or 0),
        "profile_url": f"{base}/agents/{a.name}",
        "api_key_prefix": a.api_key_prefix,
        "claimed_at": iso_utc(a.claimed_at),
    }


@router.get("/agents")
async def my_agents(
    owner: Owner = Depends(require_owner),
    session: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Agent)
        .where(Agent.owner_id == owner.id)
        .order_by(Agent.created_at.desc())
    )
    rows = (await session.execute(stmt)).scalars().all()
    base = get_settings().public_base_url.rstrip("/")
    return {
        "owner": {
            "owner_id": owner.id,
            "nickname": owner.nickname,
            "avatar_url": owner.avatar_url,
        },
        "agents": [_agent_summary(a, base) for a in rows],
    }


@router.get("/matches")
async def my_matches(
    owner: Owner = Depends(require_owner),
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
):
    """All matches involving any of this owner's agents.

    Returns the latest `limit` matches (any status), newest first — enough
    for a `/my` dashboard "recent games" strip without pagination.
    """
    agent_ids_stmt = select(Agent.id).where(Agent.owner_id == owner.id)
    agent_ids = [row[0] for row in (await session.execute(agent_ids_stmt)).all()]
    if not agent_ids:
        return {"matches": []}

    # Matches where any player.agent_id is in our set.
    match_ids_stmt = (
        select(MatchPlayer.match_id)
        .where(MatchPlayer.agent_id.in_(agent_ids))
        .distinct()
    )
    match_ids = [row[0] for row in (await session.execute(match_ids_stmt)).all()]
    if not match_ids:
        return {"matches": []}

    stmt = (
        select(Match)
        .where(Match.id.in_(match_ids))
        .order_by(Match.created_at.desc())
        .limit(limit)
    )
    matches = (await session.execute(stmt)).scalars().all()
    base = get_settings().public_base_url.rstrip("/")
    out = []
    for m in matches:
        state = m.state or {}
        players = [
            {
                "seat": p.seat,
                "name": p.name,
                "agent_id": p.agent_id,
                "is_mine": p.agent_id in agent_ids,
            }
            for p in m.players
        ]
        out.append(
            {
                "match_id": m.id,
                "status": m.status,
                "created_at": iso_utc(m.created_at),
                "move_count": state.get("move_count", 0),
                "players": players,
                "invite_url": f"{base}/match/{m.id}",
                "result": m.result,
            }
        )
    return {"matches": out}
