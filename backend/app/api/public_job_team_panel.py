"""Zespół dla klienta pod linkiem: publiczne trasy bez logowania.

Reguły: ``docs/claude/klienci/zespol-dla-klienta.md``. Odpowiedź składa
``services/job_team_panel.py`` z jawnych list pól; szczegóły osób idą przez
trasy panelu stanowiska (``/api/public/panel/{key}``). Bez
``from __future__ import annotations``: slowapi #579.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public_client_panel import (
    _NOINDEX_HEADERS,
    AuthorIn,
    InterviewIn,
    _noindex,
    _slot_note,
)
from app.core.database import get_db
from app.core.rate_limit import client_ip_key, limiter
from app.models.client_panel import ClientPanel
from app.models.job import Job
from app.models.job_team_panel import JobTeamSelection
from app.models.user import User
from app.services import client_panel as panel_service
from app.services import client_panel_requests as requests_service
from app.services import interview_slots
from app.services import job_team_panel as team_service
from app.services import job_team_variants as variants_service
from app.services.interview_slot_requests import (
    SlotsAlreadyOpen,
    after_slot_request_commit,
    create_slot_request_for_pair,
)

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
        return _bounded_picks(value)


def _bounded_picks(value: dict[str, list[str]]) -> dict[str, list[str]]:
    if not value or len(value) > team_service.MAX_JOBS:
        raise ValueError("Wybierz osoby na stanowiska zespołu.")
    if any(len(ids) > MAX_PICKED_PER_POSITION for ids in value.values()):
        raise ValueError("Za dużo osób na jednym stanowisku.")
    return value


class TeamInterviewIn(InterviewIn):
    """Jedna siatka terminów dla kilku osób zespołu."""

    picks: dict[str, list[str]]

    @field_validator("picks")
    @classmethod
    def _bounded(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        return _bounded_picks(value)


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


@router.post("/{token}/interviews")
@limiter.limit(WRITE_LIMIT)
async def post_team_interviews(
    token: str,
    body: TeamInterviewIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Rozmowy z całym składem: dla każdej osoby ta sama droga co prośba z panelu.

    Każdy wniosek idzie przez ``create_slot_request_for_pair`` jak
    ``POST /api/public/panel/{key}/candidates/{public_id}/interview`` i jest
    zatwierdzany osobno, bo wspólny serwis przy wyścigu o otwarty wniosek cofa
    całą transakcję. Osoba z czekającym wnioskiem albo ze stanowiska
    z wyłączonymi prośbami jest pominięta, nie jest błędem.
    """
    team = await team_service.load_public_team(db, token)
    positions = await team_service.public_positions(db, team)
    visible = await team_service.visible_people(db, positions)
    picks = team_service.map_picks(
        body.picks, {position.key: position.job.id for position in positions}, visible
    )
    by_job = {position.job.id: position for position in positions}
    # Limit dzienny panelu stanowiska (429) jak przy prośbie o jedną osobę;
    # stanowisko z wyłączonymi prośbami (403) pomijamy.
    blocked: set[int] = set()
    for pick in picks:
        try:
            await requests_service.guard_write(db, by_job[pick["job_id"]].panel)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_403_FORBIDDEN:
                raise
            blocked.add(pick["job_id"])
    if body.honeypot:
        return {"created": 0, "skipped": []}
    slots = interview_slots.normalize_slots(
        [slot.model_dump() for slot in body.slots],
        duration_minutes=body.duration_minutes,
        now=datetime.now(timezone.utc),
    )
    public_ids = {
        (job_id, candidate_id): public_id
        for job_id, people in visible.items()
        for public_id, candidate_id in people.items()
    }
    targets = [
        (
            by_job[pick["job_id"]].key,
            pick["job_id"],
            by_job[pick["job_id"]].panel.id,
            cid,
        )
        for pick in picks
        for cid in pick["candidate_ids"]
    ]
    created = 0
    skipped: list[dict] = []
    for key, job_id, panel_id, candidate_id in targets:
        public_id = public_ids[(job_id, candidate_id)]
        if job_id in blocked:
            skipped.append(
                {"key": key, "public_id": public_id, "reason": "actions_disabled"}
            )
            continue
        if await variants_service.has_open_request(
            db, job_id=job_id, candidate_id=candidate_id
        ):
            skipped.append(
                {"key": key, "public_id": public_id, "reason": "open_request"}
            )
            continue
        # Po commicie albo cofnięciu poprzedniej osoby obiekty trzeba wczytać.
        job = await db.get(Job, job_id)
        panel = await db.get(ClientPanel, panel_id)
        actor = (
            await db.get(User, job.delivery_lead_id) if job.delivery_lead_id else None
        )
        if actor is not None and not actor.is_active:
            actor = None
        try:
            result = await create_slot_request_for_pair(
                db,
                job=job,
                candidate_id=candidate_id,
                slots=slots,
                duration_minutes=body.duration_minutes,
                note=_slot_note(body),
                actor=actor,
            )
        except SlotsAlreadyOpen:
            skipped.append(
                {"key": key, "public_id": public_id, "reason": "open_request"}
            )
            continue
        await requests_service.create_request(
            db,
            panel=panel,
            job=job,
            kind="interview",
            author_name=body.author_name,
            author_email=str(body.author_email),
            body=body.prep_note,
            candidate_id=candidate_id,
            slot_request_id=result.request.id,
        )
        await db.commit()
        await after_slot_request_commit(db, result)
        created += 1
    await db.commit()
    return {"created": created, "skipped": skipped}
