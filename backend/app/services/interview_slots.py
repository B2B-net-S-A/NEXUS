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
from sqlalchemy import or_, select
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


async def slot_recruiter_eligible(db: AsyncSession, user_id: int, job_id: int) -> bool:
    """Czy osoba może wybierać termin z kandydatem: aktywne konto roli
    wewnętrznej z dostępem do rekrutacji.

    Jedna reguła dla rekrutera wskazanego jawnie (422 w API) i podpowiadanego
    (``default_recruiter_id``) — do rundy 2 audytu (25.09.2026) podpowiedź nie
    sprawdzała niczego, więc wniosek dostawała np. osoba, która odeszła
    z firmy, i nikt nie wybierał terminu.
    """

    from app.api.recruitment_access import (  # noqa: PLC0415 — cykl importu
        RECRUITMENT_READ_ROLES,
        ensure_job_membership,
    )
    from app.models.user import User  # noqa: PLC0415

    user = await db.get(User, user_id)
    if (
        user is None
        or not user.is_active
        or not user.has_any_role(*RECRUITMENT_READ_ROLES)
    ):
        return False
    try:
        await ensure_job_membership(db, user, job_id)
    except HTTPException:
        return False
    return True


async def default_recruiter_id(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[int]:
    """Rekruter kandydata: właściciel procesu → pierwszy weryfikator → rekruter
    rekrutacji. Ta sama kolejność co przy „Moich ludziach” (weryfikator).

    Każdy kandydat na rekrutera przechodzi ``slot_recruiter_eligible`` —
    wygrywa pierwszy, który ją spełnia; nikt = ``None`` (wniosek bez
    rekrutera wybiera zespół rekrutacji).
    """
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
    job_recruiter = await db.scalar(select(Job.recruiter_id).where(Job.id == job_id))
    seen: set[int] = set()
    for user_id in (owner, verifier, job_recruiter):
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        if await slot_recruiter_eligible(db, user_id, job_id):
            return user_id
    return None


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
    supersedes_event_id: Optional[int] = None,
) -> tuple[CalendarEvent, str]:
    """Potwierdź termin → wydarzenie `client_interview`. Zwraca (wydarzenie,
    stan Outlooka: `added` | `skipped` | `failed` | `not_requested`).

    ``supersedes_event_id``: rozmowa, którą ten termin PRZEKŁADA (jawny wybór
    DL w oknie potwierdzenia, decyzja Artura 26.09.2026). Bez niego nic nie
    jest odwoływane — para może mieć kilka rund naraz."""
    superseded: Optional[CalendarEvent] = None
    if supersedes_event_id is not None:
        superseded = next(
            (
                ev
                for ev in await replaceable_interviews(db, req, for_update=True)
                if ev.id == supersedes_event_id
            ),
            None,
        )
        if superseded is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Tej rozmowy nie można zastąpić — odbyła się już, została "
                    "odwołana albo nie dotyczy tego kandydata i rekrutacji."
                ),
            )
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
    # Rekruter wniosku sprawdzany JESZCZE RAZ przy potwierdzeniu (runda 6
    # audytu): między wyborem a potwierdzeniem mógł odejść z firmy albo stracić
    # dostęp do rekrutacji — rozmowa, telefon T+15 i debrief lądowały wtedy
    # u osoby, której nie ma. Zamiast niego ta sama podpowiedź co przy
    # zakładaniu wniosku, a bez nikogo — potwierdzający.
    recruiter = req.recruiter_id
    if recruiter and not await slot_recruiter_eligible(db, recruiter, req.job_id):
        recruiter = await default_recruiter_id(
            db, candidate_id=req.candidate_id, job_id=req.job_id
        )
    owner = recruiter or user_id

    outlook = "not_requested"
    event: Optional[CalendarEvent] = None
    if add_to_outlook and recruiter:
        event, outlook = await _create_in_outlook(
            db, owner_id=recruiter, title=title, start=start, end=end
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
    if superseded is not None:
        await _cancel_outlook_copy(db, superseded)
        superseded.status = EventStatus.cancelled
        await db.flush()

    req.status = SLOT_STATUS_CONFIRMED
    req.confirmed_at = datetime.now(timezone.utc)
    req.confirmed_by = user_id
    req.event_id = event.id
    return event, outlook


async def replaceable_interviews(
    db: AsyncSession,
    req: ClientInterviewSlotRequest,
    *,
    for_update: bool = False,
) -> list[CalendarEvent]:
    """Nieodbyte rozmowy tej pary, które nowy termin może PRZEŁOŻYĆ.

    Klient przełożył rozmowę → DL zaznacza w oknie potwierdzenia, którą
    rozmowę nowy termin zastępuje, a ta jest odwoływana (bez tego stara
    zostawała ``scheduled``: telefony T+15/T+45 i eskalacja T+2h o rozmowie,
    której nie było, a prepy liczyły się do starej rundy — runda 6 audytu).
    Nie odwołujemy niczego sami: para może mieć kilka rund naraz (decyzja
    Artura 26.09.2026).

    Tylko przyszłe ``scheduled`` — rozmowa, która już się zaczęła, mogła się
    odbyć — i tylko rozmowy założone przez NEXUS: wpis wyłącznie w NEXUSIE
    albo wydarzenie potwierdzonego wcześniej wniosku (blokada bez uczestników
    w Outlooku rekrutera, zdejmowana jak w „Odwołaj”). Cudzego spotkania
    z Outlooka z uczestnikami (np. klientem) nie odwołujemy — to wysłałoby
    odwołanie ludziom spoza firmy.
    """
    from app.services.m365.calendar import M365_SOURCE

    now = datetime.now(timezone.utc)
    confirmed_events = select(ClientInterviewSlotRequest.event_id).where(
        ClientInterviewSlotRequest.candidate_id == req.candidate_id,
        ClientInterviewSlotRequest.job_id == req.job_id,
        ClientInterviewSlotRequest.event_id.isnot(None),
    )
    stmt = (
        select(CalendarEvent)
        .where(
            CalendarEvent.candidate_id == req.candidate_id,
            CalendarEvent.job_id == req.job_id,
            CalendarEvent.event_type == EventType.client_interview,
            CalendarEvent.status == EventStatus.scheduled,
            CalendarEvent.start_time > now,
            or_(
                CalendarEvent.external_source.is_distinct_from(M365_SOURCE),
                CalendarEvent.id.in_(confirmed_events),
            ),
        )
        .order_by(CalendarEvent.start_time, CalendarEvent.id)
    )
    if for_update:
        stmt = stmt.with_for_update()
    return list((await db.scalars(stmt)).all())


async def _cancel_outlook_copy(db: AsyncSession, event: CalendarEvent) -> None:
    from app.models.m365 import M365Connection
    from app.services.m365.calendar import M365_SOURCE, cancel_graph_event

    if event.external_source != M365_SOURCE or not event.external_id:
        return
    if event.created_by is None:
        return
    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == event.created_by)
    )
    if conn is None or not conn.is_active:
        return
    try:
        async with db.begin_nested():
            await cancel_graph_event(db, conn, event.external_id)
    except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
        logger.warning(
            "interview slots: superseded interview %s not cancelled in Outlook (%s)",
            event.id,
            type(exc).__name__,
        )


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


async def slot_owner_recipients(
    db: AsyncSession, req: ClientInterviewSlotRequest
) -> list[int]:
    """Kto potwierdza termin u klienta: autor wniosku, a gdy jego konto jest
    nieaktywne — DL rekrutacji albo HoR (``_delivery_lead_targets``).

    Runda 7 (X1-4): `emit` po cichu odrzuca nieaktywnego odbiorcę, więc po
    odejściu autora wniosku dzwonek „Kandydat wybrał termin” nie docierał do
    nikogo. Bliźniak poprawki z rundy 6 w potwierdzeniu terminu.
    """
    from app.models.user import User  # noqa: PLC0415
    from app.services.notification_triggers import (  # noqa: PLC0415
        _delivery_lead_targets,
    )

    if req.created_by is not None:
        active = await db.scalar(
            select(User.is_active).where(User.id == req.created_by)
        )
        if active:
            return [req.created_by]
    job = await db.get(Job, req.job_id)
    if job is None:
        return []
    return await _delivery_lead_targets(db, job)


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
