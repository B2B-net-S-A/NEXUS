"""Zespół dla klienta pod linkiem: publiczne trasy bez logowania.

Reguły: ``docs/claude/klienci/zespol-dla-klienta.md``. Odpowiedź składa
``services/job_team_panel.py`` z jawnych list pól; szczegóły osób idą przez
trasy panelu stanowiska (``/api/public/panel/{key}``). Bez
``from __future__ import annotations``: slowapi #579.
"""

from typing import Optional

from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public_client_panel import _NOINDEX_HEADERS, AuthorIn, _noindex
from app.core.database import get_db
from app.core.rate_limit import client_ip_key, limiter
from app.models.job_team_panel import JobTeamSelection
from app.services import client_panel as panel_service
from app.services import job_team_panel as team_service

READ_LIMIT = "60/minute"
WRITE_LIMIT = "5/minute"
MAX_PICKED_PER_POSITION = 50

router = APIRouter(dependencies=[Depends(_noindex)])


class SelectionIn(AuthorIn):
    picks: dict[str, list[str]]
    note: Optional[str] = Field(None, max_length=2000)

    @field_validator("picks")
    @classmethod
    def _bounded(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if not value or len(value) > team_service.MAX_JOBS:
            raise ValueError("Wybierz osoby na stanowiska zespołu.")
        if any(len(ids) > MAX_PICKED_PER_POSITION for ids in value.values()):
            raise ValueError("Za dużo osób na jednym stanowisku.")
        return value


@router.get("/{token}")
@limiter.limit(READ_LIMIT)
async def get_team_panel(
    token: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zespół: stanowiska z listą osób, którym wysłano CV."""
    team = await team_service.load_public_team(db, token)
    positions = await team_service.public_positions(db, team)
    view = await team_service.public_team_view(db, team, positions)
    ip = client_ip_key(request)
    for position in positions:
        await panel_service.log_view(
            db, panel_id=position.panel.id, action="open", ip=ip
        )
    await db.commit()
    return view


@router.post("/{token}/selection", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(WRITE_LIMIT)
async def post_selection(
    token: str,
    body: SelectionIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Wybrany skład; decyzja i dalsze kroki zostają u Delivery Leada."""
    team = await team_service.load_public_team(db, token)
    await team_service.guard_selection_write(db, team)
    if body.honeypot:
        return Response(
            status_code=status.HTTP_204_NO_CONTENT, headers=_NOINDEX_HEADERS
        )
    positions = await team_service.public_positions(db, team)
    picks = team_service.map_picks(
        body.picks,
        {position.key: position.job.id for position in positions},
        await team_service.visible_people(db, positions),
    )
    row = JobTeamSelection(
        team_id=team.id,
        picks=picks,
        author_name=body.author_name,
        author_email=str(body.author_email).strip().lower(),
        note=(body.note or "").strip() or None,
        ip_hash=panel_service.hash_ip(client_ip_key(request)),
    )
    db.add(row)
    await db.flush()
    await team_service.notify_selection(
        db, team, row, [position.job for position in positions]
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_NOINDEX_HEADERS)
