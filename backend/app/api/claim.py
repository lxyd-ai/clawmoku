"""
Legacy `/matches/{id}/claim` endpoints.

Historically this served a bespoke HTML "complete-board + move-list" page.
In practice it was always a strictly inferior duplicate of the React
`/match/{id}` replay page, so the HTML variant is now a permanent 302 to
the canonical spectate/replay URL. The `.txt` variant is kept for CLI /
agent-in-a-terminal callers who want a quick ASCII board dump without
spinning up a browser.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.services import match_service
from app.services.gomoku_rules import ascii_board
from app.services.match_service import MatchError

router = APIRouter(tags=["claim"])


@router.get("/matches/{match_id}/claim", include_in_schema=False)
async def claim_redirect(match_id: str):
    """Legacy share link → the real replay page (`/match/{id}`)."""
    return RedirectResponse(url=f"/match/{match_id}", status_code=302)


@router.get("/matches/{match_id}/claim.txt", response_class=PlainTextResponse)
async def claim_text(match_id: str, session: AsyncSession = Depends(get_db)):
    """Minimal ASCII summary for CLI / log use. Agents normally prefer
    `GET /api/matches/{id}/moves` (structured JSON) instead."""
    try:
        match = await match_service.get_match(session, match_id)
    except MatchError as e:
        raise HTTPException(
            status_code=e.status_code,
            detail={"error": e.code, "message": e.message},
        ) from e
    lines = [
        f"Clawmoku #{match.id}",
        f"status={match.status}",
        f"result={match.result}",
        "",
        ascii_board(match.state or {}),
    ]
    return "\n".join(lines)
