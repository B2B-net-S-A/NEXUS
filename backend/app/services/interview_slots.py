"""Przejścia wniosku o terminy rozmowy u klienta (0338).

    awaiting_recruiter ──wybór rekrutera──▶ awaiting_dl ──potwierdzenie DL──▶ confirmed
            │                                   │
            └────────────── anulowanie ─────────┴──▶ cancelled

Każde przejście blokuje wiersz (`FOR UPDATE`) i sprawdza stan źródłowy pod
blokadą — dwa kliknięcia „Potwierdź” nie założą dwóch rozmów w kalendarzu.
DL może potwierdzić termin od razu z `awaiting_recruiter`, podając indeks
(klient oddzwonił z jednym terminem, nie ma czego wybierać).

Potwierdzenie zakłada wydarzenie ``client_interview`` z właścicielem =
rekruter. Gdy rekruter ma połączoną skrzynkę, wydarzenie ląduje też w jego
Outlooku jako blokada BEZ uczestników — kandydata zaprasza klient, my nie
wysyłamy mu drugiego zaproszenia.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client_interview_slot_request import (
    SLOT_STATUS_AWAITING_DL,
    SLOT_STATUS_AWAITING_RECRUITER,
    SLOT_STATUS_CANCELLED,
    SLOT_STATUS_CONFIRMED,
    ClientInterviewSlotRequest,
)
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.recruitment_process import RecruitmentProcess

logger = logging.getLogger(__name__)

MAX_SLOTS = 6
SLOT_ENTITY = "interview_slot_request"


def cycle_link(candidate_id: int, job_id: int) -> str:
    return f"/calendar?cycle={candidate_id}-{job_id}"


def normalize_slots(
    raw: list[dict], *, duration_minutes: int, now: datetime
) -> list[dict]:
    """Terminy z formularza → [{start, end}] w ISO UTC, posortowane, bez duplikatów.

    Termin z przeszłości jest błędem wpisu (klient podaje przyszłe sloty) —
    odrzucamy go jawnie, zamiast po cichu wyrzucać, bo DL musiałby zgadywać,
    który z jego terminów zniknął.
    """
    if not raw:
        raise HTTPException(status_code=422, detail="Podaj co najmniej jeden termin.")
    if len(raw) > MAX_SLOTS:
        raise HTTPException(
            status_code=422, detail=f"Najwyżej {MAX_SLOTS} terminów na jeden wniosek."
        )
    out: dict[str, dict] = {}
    for item in raw:
        start = item["start"]
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = item.get("end")
        if end is None:
            end = start + timedelta(minutes=duration_minutes)
        elif end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        if end <= start:
            raise HTTPException(
                status_code=422,
                detail="Koniec terminu musi być późniejszy niż jego początek.",
            )
        if start < now - timedelta(minutes=5):
            raise HTTPException(
                status_code=422, detail="Termin rozmowy nie może być w przeszłości."
            )
        start_utc = start.astimezone(timezone.utc)
        out[start_utc.isoformat()] = {
            "start": start_utc.isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
        }
    return [out[k] for k in sorted(out)]


async def default_recruiter_id(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[int]:
    """Rekruter kandydata: właściciel procesu → pierwszy weryfikator → rekruter
    rekrutacji. Ta sama kolejność co przy „Moich ludziach” (weryfikator)."""
    owner = await db.scalar(
        select(RecruitmentProcess.owner_user_id)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
            RecruitmentProcess.owner_user_id.isnot(None),
        )
        .order_by(RecruitmentProcess.id.desc())
        .limit(1)
    )
    if owner:
        return owner
    verifier = await db.scalar(
        select(CandidateStage.moved_by)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
            CandidateStage.stage == PipelineStage.verified,
            CandidateStage.moved_by.isnot(None),
        )
        .order_by(CandidateStage.moved_at.asc(), CandidateStage.id.asc())
        .limit(1)
    )
    if verifier:
        return verifier
    return await db.scalar(select(Job.recruiter_id).where(Job.id == job_id))


async def pair_in_pipeline(db: AsyncSession, *, candidate_id: int, job_id: int) -> bool:
    return (
        await db.scalar(
            select(CandidateStage.id)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .limit(1)
        )
    ) is not None


async def lock_request(db: AsyncSession, request_id: int) -> ClientInterviewSlotRequest:
    req = await db.scalar(
        select(ClientInterviewSlotRequest)
        .where(ClientInterviewSlotRequest.id == request_id)
        .with_for_update()
    )
    if req is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono wniosku o terminy.")
    return req


def _parse(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def choose(req: ClientInterviewSlotRequest, index: int, *, user_id: int) -> None:
    if req.status != SLOT_STATUS_AWAITING_RECRUITER:
        raise HTTPException(
            status_code=409,
            detail=_status_conflict(req.status),
        )
    _check_index(req, index)
    req.chosen_index = index
    req.chosen_at = datetime.now(timezone.utc)
    req.chosen_by = user_id
    req.status = SLOT_STATUS_AWAITING_DL


def _check_index(req: ClientInterviewSlotRequest, index: int) -> None:
    if not 0 <= index < len(req.slots or []):
        raise HTTPException(status_code=422, detail="Nie ma takiego terminu.")


def _status_conflict(status: str) -> str:
    return {
        SLOT_STATUS_AWAITING_DL: "Termin jest już wybrany — czeka na potwierdzenie DL.",
        SLOT_STATUS_CONFIRMED: "Termin jest już potwierdzony u klienta.",
        SLOT_STATUS_CANCELLED: "Wniosek o terminy został anulowany.",
        SLOT_STATUS_AWAITING_RECRUITER: "Rekruter nie wybrał jeszcze terminu.",
    }.get(status, "Wniosek jest w innym stanie.")


async def confirm(
    db: AsyncSession,
    req: ClientInterviewSlotRequest,
    *,
    user_id: int,
    index: Optional[int],
    add_to_outlook: bool,
) -> tuple[CalendarEvent, str]:
    """Potwierdź termin → wydarzenie `client_interview`. Zwraca (wydarzenie,
    stan Outlooka: `added` | `skipped` | `failed` | `not_requested`)."""
    if req.status == SLOT_STATUS_AWAITING_RECRUITER:
        if index is None:
            raise HTTPException(status_code=409, detail=_status_conflict(req.status))
        _check_index(req, index)
        req.chosen_index = index
        req.chosen_at = datetime.now(timezone.utc)
        req.chosen_by = user_id
    elif req.status != SLOT_STATUS_AWAITING_DL:
        raise HTTPException(status_code=409, detail=_status_conflict(req.status))
    elif index is not None and index != req.chosen_index:
        # DL potwierdza INNY termin niż wybrał rekruter (klient go odrzucił).
        _check_index(req, index)
        req.chosen_index = index

    slot = req.slots[req.chosen_index]
    start, end = _parse(slot["start"]), _parse(slot["end"])
    candidate = await db.get(Candidate, req.candidate_id)
    job = await db.get(Job, req.job_id)
    title = _interview_title(candidate, job)
    owner = req.recruiter_id or user_id

    outlook = "not_requested"
    event: Optional[CalendarEvent] = None
    if add_to_outlook and req.recruiter_id:
        event, outlook = await _create_in_outlook(
            db, owner_id=req.recruiter_id, title=title, start=start, end=end
        )
    if event is None:
        event = CalendarEvent(
            title=title,
            event_type=EventType.client_interview,
            start_time=start,
            end_time=end,
            all_day=False,
            status=EventStatus.scheduled,
            external_source="manual",
            created_by=owner,
            attendees=[],
        )
        db.add(event)
    event.event_type = EventType.client_interview
    event.candidate_id = req.candidate_id
    event.job_id = req.job_id
    event.client_id = req.client_id
    event.operational_owner_id = owner
    event.reminder_minutes = 15
    event.description = _interview_description(req)
    await db.flush()

    req.status = SLOT_STATUS_CONFIRMED
    req.confirmed_at = datetime.now(timezone.utc)
    req.confirmed_by = user_id
    req.event_id = event.id
    return event, outlook


def _interview_title(candidate: Optional[Candidate], job: Optional[Job]) -> str:
    who = (
        " ".join(p for p in (candidate.name, candidate.lastname) if p)
        if candidate
        else "Kandydat"
    ) or "Kandydat"
    what = job.title if job else "rekrutacja"
    return f"Rozmowa u klienta: {who} — {what}"[:255]


def _interview_description(req: ClientInterviewSlotRequest) -> str:
    lines = [
        "Rozmowa kandydata u klienta (termin potwierdzony przez DL w NEXUSIE).",
        "Zadzwoń do kandydata najpóźniej 30 min po rozmowie i zapisz debrief.",
    ]
    if req.note:
        lines.append(f"Notatka DL: {req.note}")
    return "\n".join(lines)


async def _create_in_outlook(
    db: AsyncSession,
    *,
    owner_id: int,
    title: str,
    start: datetime,
    end: datetime,
) -> tuple[Optional[CalendarEvent], str]:
    """Blokada w Outlooku rekrutera. Awaria nie blokuje potwierdzenia —
    termin u klienta JEST ustalony, a wpis w NEXUSIE i tak powstanie."""
    from app.models.m365 import M365Connection
    from app.services.m365.calendar import create_event as m365_create_event

    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == owner_id)
    )
    if conn is None or not conn.is_active:
        return None, "skipped"
    try:
        async with db.begin_nested():
            row = await m365_create_event(
                db,
                conn,
                candidate=None,
                title=title,
                description="Rozmowa kandydata u klienta — blokada w kalendarzu.",
                start=start,
                end=end,
                event_type=EventType.client_interview,
                invite_candidate=False,
                with_teams_meeting=False,
            )
        return row, "added"
    except Exception:  # noqa: BLE001 — Graph, sieć, token
        logger.exception("interview slots: Outlook block failed for user %s", owner_id)
        return None, "failed"


def cancel(req: ClientInterviewSlotRequest) -> None:
    if req.status not in (SLOT_STATUS_AWAITING_RECRUITER, SLOT_STATUS_AWAITING_DL):
        raise HTTPException(status_code=409, detail=_status_conflict(req.status))
    req.status = SLOT_STATUS_CANCELLED


async def notify(
    db: AsyncSession,
    *,
    user_id: Optional[int],
    ntype: NotificationType,
    req: ClientInterviewSlotRequest,
    title: str,
    message: str,
    actor_id: int,
) -> None:
    """Dzwonek przekazania — nigdy do osoby, która sama kliknęła."""
    if not user_id or user_id == actor_id:
        return
    from app.services.notification_triggers import emit

    try:
        async with db.begin_nested():
            await emit(
                db,
                user_id=user_id,
                title=title,
                message=message,
                ntype=ntype,
                related_entity_type=SLOT_ENTITY,
                related_entity_id=req.id,
                link=cycle_link(req.candidate_id, req.job_id),
            )
    except Exception:  # noqa: BLE001 — dzwonek nie może cofnąć przejścia
        logger.exception("interview slots: notification failed for request %s", req.id)
