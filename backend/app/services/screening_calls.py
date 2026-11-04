"""Umówiony telefon na screening (decyzja Artura 03.11.2026, wariant A).

Kandydat prosi o kontakt jutro albo później. Do tej pory rekruter pisał to
w notatce, której NEXUS nie rozumiał, a blokada 12 h wygasała przed telefonem.

Termin to zwykłe wydarzenie `screening` z miejscem „Telefon”
(`models/calendar_event.py`), więc przypomnienie, kalendarz, zastępstwa i dane
kandydata przy usunięciu działają jak przy każdym innym wydarzeniu. Tu są tylko
reguły, których tamte ścieżki nie znają:

- jedna para (osoba, rekrutacja) ma najwyżej jeden otwarty termin;
- termin trzyma osobę przy rekruterze do startu + 30 min, najwyżej 7 dni;
- zapis screeningu kończy termin od razu, a ruch karty i zamknięcie rekrutacji
  przy następnym przebiegu pętli przypomnień (`reconcile`), bez dotykania
  kilkunastu ścieżek ruchu karty;
- w Outlooku rekrutera jest sama blokada, bez kandydata na liście uczestników
  i bez Teams, a jej zdjęcie też robi pętla (`clean_outlook`).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import (
    BOOKED_CALL_LOCATION,
    CalendarEvent,
    EventStatus,
    EventType,
    is_booked_call,
)
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.m365 import M365Connection
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User
from app.models.activity import Activity
from app.services import candidate_claim
from app.services.autofill_decisions import record_call
from app.services.m365.calendar import (
    M365_SOURCE,
    _build_event_payload,
    build_update_payload,
    cancel_graph_event,
    event_transaction_id,
    update_graph_event,
)
from app.services.m365.graph_client import GraphClient
from app.services.m365.oauth import M365ReauthRequired
from app.services.workforce_availability import effective_owner_ids

logger = logging.getLogger(__name__)

CALL_MINUTES = 15
REMINDER_MINUTES = 15
# Dalszy termin to już nie „proszę później”, tylko inna rozmowa (jak follow-up).
MAX_DAYS_AHEAD = 60
HOLD_AFTER_START = timedelta(minutes=30)
HOLD_MAX = timedelta(days=7)
HOUSEKEEPING_BATCH = 200
# Zdejmowanie z Outlooka mieści się w jednym przebiegu pętli przypomnień:
# jedno wywołanie Grapha może trwać do 120 s, a pętla nie może na nie czekać.
OUTLOOK_CLEAN_BATCH = 20
OUTLOOK_CLEAN_TIMEOUT_SECONDS = 30

OutlookResult = Literal["added", "updated", "not_connected", "failed"]


@dataclass(frozen=True)
class BookedCall:
    event_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    job_working_title: Optional[str]
    client_name: Optional[str]
    start_time: datetime
    note: Optional[str]
    owner_id: Optional[int]
    in_outlook: bool


def panel_link(job_id: int, candidate_id: int) -> str:
    return f"/jobs/{job_id}?candidate={candidate_id}"


def outlook_subject(candidate: Candidate) -> str:
    """Tytuł w Outlooku: imię i inicjał, bo ten wpis żyje poza NEXUSEM."""
    first = (candidate.name or "").strip()
    last = (candidate.lastname or "").strip()
    short = f"{first} {last[0]}." if first and last else first or last
    return f"Telefon: {short}" if short else "Telefon do kandydata"


def _full_name(candidate: Candidate) -> str:
    return f"{candidate.name or ''} {candidate.lastname or ''}".strip()


def hold_until(start: datetime, now: datetime) -> datetime:
    """Do kiedy termin trzyma osobę. Nigdy krócej niż zwykłe „Biorę”."""
    return max(
        now + timedelta(hours=candidate_claim.CLAIM_HOURS),
        min(start + HOLD_AFTER_START, now + HOLD_MAX),
    )


def _open_calls_clause():
    return (
        CalendarEvent.event_type == EventType.screening,
        CalendarEvent.location == BOOKED_CALL_LOCATION,
        CalendarEvent.operational_owner_id.is_not(None),
        CalendarEvent.status == EventStatus.scheduled,
    )


def _assert_valid_start(start: datetime, now: datetime) -> None:
    if start.tzinfo is None:
        raise HTTPException(status_code=422, detail="Podaj termin ze strefą czasową.")
    if start <= now:
        raise HTTPException(
            status_code=422, detail="Termin telefonu musi być w przyszłości."
        )
    if start > now + timedelta(days=MAX_DAYS_AHEAD):
        raise HTTPException(
            status_code=422,
            detail=f"Telefon można umówić najdalej za {MAX_DAYS_AHEAD} dni.",
        )


def _clean_note(note: Optional[str]) -> Optional[str]:
    text = (note or "").strip()
    return text or None


async def _active_connection(
    db: AsyncSession, user_id: int
) -> Optional[M365Connection]:
    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )
    return conn if conn is not None and conn.is_active else None


async def _locked_pair(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> tuple[Candidate, Optional[RecruitmentProcess], Optional[CandidateStage]]:
    """Ta sama kolejność blokad co `/claim` i `/move`: kandydat, potem proces."""
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje.")
    process = await db.scalar(
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(RecruitmentProcess.attempt_no.desc(), RecruitmentProcess.id.desc())
        .limit(1)
        .with_for_update()
    )
    latest = await _latest_stage(db, candidate_id=candidate_id, job_id=job_id)
    return candidate, process, latest


async def _latest_stage(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def _in_entry_column(
    db: AsyncSession,
    process: Optional[RecruitmentProcess],
    latest: Optional[CandidateStage],
) -> bool:
    return (
        process is not None
        and latest is not None
        and process.status == ProcessStatus.open
        and await candidate_claim.stage_column(db, latest)
        in candidate_claim.CLAIM_COLUMNS
    )


async def book(
    db: AsyncSession,
    *,
    user: User,
    job: Job,
    candidate_id: int,
    start: datetime,
    note: Optional[str],
) -> CalendarEvent:
    """Umów telefon. Bez commitu — robi go trasa, a Outlook idzie po nim."""
    now = datetime.now(timezone.utc)
    _assert_valid_start(start, now)
    candidate, process, latest = await _locked_pair(
        db, candidate_id=candidate_id, job_id=job.id
    )
    if job.status == JobStatus.closed or not await _in_entry_column(
        db, process, latest
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Telefon można umówić tylko dla osoby z kolumny „Nowi” albo "
                "„Screening” w otwartym procesie."
            ),
        )
    existing = await db.scalar(
        select(CalendarEvent.id).where(
            *_open_calls_clause(),
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job.id,
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail="Ta osoba ma już umówiony telefon w tej rekrutacji. Możesz go przełożyć.",
        )
    state = candidate_claim.claim_state(
        process, await candidate_claim.inactive_holders(db, [process])
    )
    # Cudzej blokady termin nie przejmuje, także dla Delivery Leada: ma do tego
    # „Przejmij” z dzwonkiem do poprzedniej osoby.
    if state.active(now) and state.user_id != user.id:
        await candidate_claim.assert_can_act(db, process=process, user=user, now=now)
        raise HTTPException(
            status_code=409,
            detail="Tę osobę prowadzi ktoś inny. Najpierw ją przejmij.",
        )

    event = _new_event(
        user=user, candidate=candidate, job=job, start=start, note=_clean_note(note)
    )
    db.add(event)
    await db.flush()
    newly_taken = not (state.active(now) and state.user_id == user.id)
    process.claimed_by_user_id = user.id
    process.claimed_until = hold_until(start, now)
    # Osoba od systemu: umówienie to ta sama decyzja co „Dzwonię”.
    record_call(process, user.id, now)
    if newly_taken:
        db.add(
            Activity(
                entity_type="pipeline",
                entity_id=latest.id,
                action="candidate_claimed",
                user_id=user.id,
                details={
                    "candidate_id": candidate_id,
                    "job_id": job.id,
                    "taken_over_from": None,
                    "claimed_until": process.claimed_until.isoformat(),
                },
            )
        )
    db.add(
        Activity(
            entity_type="pipeline",
            entity_id=latest.id,
            action="screening_call_booked",
            user_id=user.id,
            details={
                "candidate_id": candidate_id,
                "job_id": job.id,
                "event_id": event.id,
                "start": start.isoformat(),
            },
        )
    )
    await db.flush()
    return event


def _new_event(
    *,
    user: User,
    candidate: Candidate,
    job: Job,
    start: datetime,
    note: Optional[str],
) -> CalendarEvent:
    return CalendarEvent(
        title=f"Telefon: {_full_name(candidate)}"[:255],
        description=note,
        event_type=EventType.screening,
        start_time=start,
        end_time=start + timedelta(minutes=CALL_MINUTES),
        all_day=False,
        attendees=[],
        candidate_id=candidate.id,
        job_id=job.id,
        location=BOOKED_CALL_LOCATION,
        status=EventStatus.scheduled,
        external_source="manual",
        created_by=user.id,
        operational_owner_id=user.id,
        reminder_minutes=REMINDER_MINUTES,
    )


def _outlook_body(job_id: int, candidate_id: int) -> str:
    return f"Otwórz w NEXUSIE: {settings.PUBLIC_BASE_URL}{panel_link(job_id, candidate_id)}"


async def load_call(db: AsyncSession, event_id: int) -> CalendarEvent:
    """Telefon pod blokadą, w kolejności zapisu screeningu: kandydat, potem wiersz."""
    event = await db.get(CalendarEvent, event_id)
    if event is None or not is_booked_call(event):
        raise HTTPException(status_code=404, detail="Nie ma takiego telefonu.")
    if event.candidate_id is not None:
        await db.scalar(
            select(Candidate.id)
            .where(Candidate.id == event.candidate_id)
            .with_for_update()
        )
    await db.refresh(event, with_for_update=True)
    if event.status != EventStatus.scheduled:
        raise HTTPException(
            status_code=409, detail="Ten telefon jest już zamknięty albo odwołany."
        )
    return event


async def assert_can_manage(db: AsyncSession, event: CalendarEvent, user: User) -> None:
    """Przekłada i odwołuje właściciel, jego zastępstwo, DL, HoR i admin."""
    if candidate_claim.can_override(user):
        return
    if event.operational_owner_id in await effective_owner_ids(db, user.id):
        return
    raise HTTPException(status_code=403, detail="To telefon innej osoby.")


async def reschedule(
    db: AsyncSession,
    *,
    event: CalendarEvent,
    start: datetime,
    note: Optional[str],
    note_given: bool,
) -> None:
    """Przełóż termin. Bez commitu — robi go trasa, a Outlook idzie po nim."""
    now = datetime.now(timezone.utc)
    _assert_valid_start(start, now)
    end = start + timedelta(minutes=CALL_MINUTES)
    event.start_time = start
    event.end_time = end
    event.reminder_sent_at = None
    if note_given:
        event.description = _clean_note(note)
    await extend_hold(db, event, now)
    await db.flush()


async def add_to_outlook(
    db: AsyncSession, *, event: CalendarEvent, candidate_id: int, client_request_id: str
) -> OutlookResult:
    """Blokada w Outlooku rekrutera, po commicie terminu.

    GraphClient zatwierdza sesję przy odświeżeniu tokenu, więc to wywołanie nie
    może stać w transakcji z blokadą wiersza. Termin w NEXUSIE już jest: awaria
    Outlooka kończy się informacją, a nie błędem zapisu.
    """
    conn = await _active_connection(db, event.created_by)
    if conn is None:
        return "not_connected"
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        return "failed"
    subject = outlook_subject(candidate)
    payload = _build_event_payload(
        title=subject,
        description=_outlook_body(event.job_id, candidate_id),
        start=event.start_time,
        end=event.end_time,
        attendee_emails=[],
        want_teams=False,
        transaction_id=event_transaction_id(
            owner_user_id=conn.user_id,
            title=subject,
            start=event.start_time,
            end=event.end_time,
            attendee_emails=[],
            intent_id=f"booked-call|{conn.user_id}|{client_request_id}",
        ),
    )
    try:
        async with GraphClient(conn, db) as client:
            created = await client.post("/me/events", json=payload)
        event.external_source = M365_SOURCE
        event.external_id = created["id"]
        event.m365_change_key = created.get("changeKey")
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
        await db.rollback()
        logger.warning(
            "booked call: Outlook entry not created (%s)", type(exc).__name__
        )
        return "failed"
    return "added"


async def move_in_outlook(db: AsyncSession, event: CalendarEvent) -> OutlookResult:
    """Przesuń blokadę w Outlooku, po commicie nowego terminu."""
    if not event.external_id or event.created_by is None:
        return "not_connected"
    conn = await _active_connection(db, event.created_by)
    if conn is None:
        return "not_connected"
    try:
        change_key = await update_graph_event(
            db,
            conn,
            event.external_id,
            build_update_payload(start=event.start_time, end=event.end_time),
        )
        if change_key:
            event.m365_change_key = change_key
        await db.commit()
    except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
        await db.rollback()
        logger.warning("booked call: Outlook entry not moved (%s)", type(exc).__name__)
        return "failed"
    return "updated"


async def extend_hold(db: AsyncSession, event: CalendarEvent, now: datetime) -> None:
    """Po zmianie terminu blokada idzie za nim, jeśli osoba jest przy właścicielu."""
    if event.candidate_id is None or event.job_id is None:
        return
    process = await candidate_claim.load_process(
        db, candidate_id=event.candidate_id, job_id=event.job_id
    )
    if process is not None and process.claimed_by_user_id in (
        None,
        event.operational_owner_id,
    ):
        process.claimed_by_user_id = event.operational_owner_id
        process.claimed_until = hold_until(event.start_time, now)


async def release_hold(db: AsyncSession, event: CalendarEvent, now: datetime) -> None:
    """Termin zniknął, więc nie trzyma już osoby dłużej niż zwykłe „Biorę”."""
    if event.candidate_id is None or event.job_id is None:
        return
    process = await candidate_claim.load_process(
        db, candidate_id=event.candidate_id, job_id=event.job_id
    )
    if process is None or process.claimed_by_user_id != event.operational_owner_id:
        return
    latest = now + timedelta(hours=candidate_claim.CLAIM_HOURS)
    if process.claimed_until is not None and process.claimed_until > latest:
        process.claimed_until = latest


async def complete_for_pair(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> None:
    """Zapis screeningu kończy termin. Blokadę w Outlooku zdejmie pętla."""
    events = (
        await db.scalars(
            select(CalendarEvent).where(
                *_open_calls_clause(),
                CalendarEvent.candidate_id == candidate_id,
                CalendarEvent.job_id == job_id,
            )
        )
    ).all()
    now = datetime.now(timezone.utc)
    for event in events:
        event.status = EventStatus.completed
        await release_hold(db, event, now)


async def follow_claim(
    db: AsyncSession,
    *,
    process: RecruitmentProcess,
    user: User,
    now: datetime,
) -> None:
    """„Biorę” i „Przejmij”: telefon idzie z osobą.

    Stary wiersz zostaje odwołany, żeby pętla zdjęła blokadę z Outlooka
    poprzedniej osoby. Nowy powstaje bez wpisu w Outlooku, bo ta trasa nie
    woła Grapha. Przypomnienie, lista i przełożenie są już u nowego prowadzącego.
    """
    event = await db.scalar(
        select(CalendarEvent)
        .where(
            *_open_calls_clause(),
            CalendarEvent.candidate_id == process.candidate_id,
            CalendarEvent.job_id == process.job_id,
        )
        .limit(1)
        .with_for_update()
    )
    if event is None:
        return
    if event.operational_owner_id != user.id:
        event.status = EventStatus.cancelled
        event = CalendarEvent(
            title=event.title,
            description=event.description,
            event_type=EventType.screening,
            start_time=event.start_time,
            end_time=event.end_time,
            all_day=False,
            attendees=[],
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            location=BOOKED_CALL_LOCATION,
            status=EventStatus.scheduled,
            external_source="manual",
            created_by=user.id,
            operational_owner_id=user.id,
            reminder_minutes=event.reminder_minutes,
        )
        db.add(event)
    process.claimed_until = hold_until(event.start_time, now)


async def reconcile(db: AsyncSession) -> int:
    """Termin osoby, która poszła dalej albo odpadła, nie może dzwonić.

    Karta rusza się kilkunastoma ścieżkami (przesunięcie, automaty, poczta CPro,
    import, zamknięcie rekrutacji), więc stan czytamy z efektu, a nie z każdej
    z nich. Otwartych terminów jest niewiele i pętla przechodzi je co minutę.
    """
    events = (
        await db.scalars(
            select(CalendarEvent)
            .where(*_open_calls_clause())
            .order_by(CalendarEvent.start_time)
            .limit(HOUSEKEEPING_BATCH)
        )
    ).all()
    changed = 0
    for event in events:
        verdict = await _closing_status(db, event)
        if verdict is not None:
            event.status = verdict
            changed += 1
    if changed:
        await db.commit()
    return changed


async def _closing_status(
    db: AsyncSession, event: CalendarEvent
) -> Optional[EventStatus]:
    if event.candidate_id is None or event.job_id is None:
        return EventStatus.cancelled
    job = await db.get(Job, event.job_id)
    if job is None or job.status == JobStatus.closed or job.work_state == "finished":
        return EventStatus.cancelled
    process = await candidate_claim.load_process(
        db, candidate_id=event.candidate_id, job_id=event.job_id
    )
    if process is None or process.status != ProcessStatus.open:
        return EventStatus.cancelled
    latest = await _latest_stage(
        db, candidate_id=event.candidate_id, job_id=event.job_id
    )
    if latest is None:
        return EventStatus.cancelled
    if await candidate_claim.stage_column(db, latest) in candidate_claim.CLAIM_COLUMNS:
        return None
    return EventStatus.completed


async def clean_outlook(db: AsyncSession, now: datetime) -> int:
    """Zdejmij z Outlooka blokady telefonów, które już nie obowiązują.

    Tylko przyszłe: minione zostają w historii kalendarza rekrutera. Błąd Grapha
    zostawia wiersz na następny przebieg, a brak połączenia odpina kopię, bo nie
    ma już czym jej zdjąć.
    """
    events = (
        await db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.event_type == EventType.screening,
                CalendarEvent.location == BOOKED_CALL_LOCATION,
                CalendarEvent.operational_owner_id.is_not(None),
                CalendarEvent.status != EventStatus.scheduled,
                CalendarEvent.external_id.is_not(None),
                CalendarEvent.start_time > now,
            )
            .order_by(CalendarEvent.start_time)
            .limit(OUTLOOK_CLEAN_BATCH)
        )
    ).all()
    cleaned = 0
    for event in events:
        conn = (
            await _active_connection(db, event.created_by)
            if event.created_by is not None
            else None
        )
        if conn is not None:
            try:
                await cancel_graph_event(
                    db, conn, event.external_id, comment="Telefon odwołany."
                )
            except M365ReauthRequired:
                pass
            except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
                logger.warning(
                    "booked call: Outlook entry not removed (%s)", type(exc).__name__
                )
                continue
        event.external_source = None
        event.external_id = None
        event.m365_change_key = None
        await db.commit()
        cleaned += 1
    return cleaned


async def reconcile_open_calls() -> None:
    """Przed skanem przypomnień, sama baza: telefon osoby, która poszła dalej, nie dzwoni."""
    async with AsyncSessionLocal() as db:
        await reconcile(db)


async def clean_outlook_copies(now: datetime) -> None:
    """Po wysyłce przypomnień i z limitem czasu: Graph nie może ich wstrzymać."""

    async def run() -> None:
        async with AsyncSessionLocal() as db:
            await clean_outlook(db, now)

    try:
        await asyncio.wait_for(run(), timeout=OUTLOOK_CLEAN_TIMEOUT_SECONDS)
    except TimeoutError:
        logger.warning("booked call: Outlook cleanup timed out, next pass continues")


async def starts_by_candidate(
    db: AsyncSession, job_id: int, candidate_ids: list[int]
) -> dict[int, CalendarEvent]:
    """Otwarte terminy jednej Tablicy — jedno zapytanie."""
    if not candidate_ids:
        return {}
    rows = (
        await db.scalars(
            select(CalendarEvent).where(
                *_open_calls_clause(),
                CalendarEvent.job_id == job_id,
                CalendarEvent.candidate_id.in_(candidate_ids),
            )
        )
    ).all()
    return {event.candidate_id: event for event in rows}


async def for_user(db: AsyncSession, user: User) -> list[BookedCall]:
    """Telefony tej osoby i tych, których zastępuje, od najstarszego terminu."""
    owners = await effective_owner_ids(db, user.id)
    rows = (
        await db.execute(
            select(CalendarEvent, Candidate, Job, Client.name)
            .join(Candidate, Candidate.id == CalendarEvent.candidate_id)
            .join(Job, Job.id == CalendarEvent.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .where(
                *_open_calls_clause(),
                CalendarEvent.operational_owner_id.in_(owners),
                Job.status != JobStatus.closed,
            )
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
            .limit(HOUSEKEEPING_BATCH)
        )
    ).all()
    return [
        BookedCall(
            event_id=event.id,
            candidate_id=candidate.id,
            candidate_name=_full_name(candidate),
            job_id=job.id,
            job_title=job.title,
            job_working_title=job.working_title,
            client_name=client_name,
            start_time=event.start_time,
            note=event.description,
            owner_id=event.operational_owner_id,
            in_outlook=bool(event.external_id),
        )
        for event, candidate, job, client_name in rows
    ]


async def for_user_safely(db: AsyncSession, user: User) -> list[BookedCall]:
    """Awaria tej listy nie może położyć pulpitu (jak follow-upy)."""
    try:
        async with db.begin_nested():
            return await for_user(db, user)
    except Exception:  # noqa: BLE001
        logger.exception("booked calls failed to load")
        return []
