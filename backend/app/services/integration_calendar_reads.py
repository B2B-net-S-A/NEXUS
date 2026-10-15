"""Odczyty kalendarza rozmów u klienta dla API v1 (``api/integrations_v1/calendar``).

Zapytania i projekcje bez żądania i bez użytkownika. Zakres wyznaczają scope'y
klucza, nie ``_scope_pairs`` ekranu (ten liczy pary jednej osoby). Kroki, fazę
i rundy liczą te same funkcje co ekran „Rozmowy u klienta” i plakietka na
Tablicy (``services/interview_cycle``: ``load_snapshots``, ``compute_steps``,
``compute_badge`` + ``badge_phase``, ``assign_prep_ordinals``; zamknięcie
rundy — ``debrief_gate.debrief_closes_round``). Ten moduł niczego nie liczy
po swojemu poza wyborem prepów jednej rozmowy (lustro ``_round_preps``
i ``_late_preps`` z ``load_snapshots``, które działają tylko na bieżącej rundzie).

Reguły, które łatwo cofnąć:

* Z wydarzenia wychodzą tylko termin, status i para (kandydat, rekrutacja).
  Tytuł, opis, miejsce, uczestnicy (e-maile) i linki spotkań nie wychodzą
  nigdy: wydarzenie z Outlooka bywa prywatne (``calendar_privacy``), a opis
  rozmowy niesie notatkę DL-a z wniosku o terminy.
* Debrief: flagi zawsze, treść (komentarz kandydata, pytania klienta) tylko
  z ``notes:read``. Ekran pokazuje ją każdej roli z odczytem rekrutacji
  (``GET /api/interview-cycle/events/{id}/debrief``), więc dla klucza to
  odpowiednik notatek. Warunek kandydata (``acceptance_condition``) to zwykle
  stawka albo warunki umowy, więc wymaga też ``amounts:read`` (koszt).
* Rozmowy rekrutacji klienta ukrytego albo usuniętego nie istnieją dla klucza
  (``jobs_register_base_clause``, jak rejestr rekrutacji).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.job import Job
from app.models.prep_meeting import PrepMeeting, PrepReview
from app.services.client_identity import client_display_name_expression
from app.services.debrief_gate import debrief_closes_round
from app.services.interview_cycle import (
    BADGE_DAYS_AHEAD,
    DEFAULT_DAYS_BACK,
    MAX_PAIRS,
    DebriefRef,
    EventRef,
    PairSnapshot,
    _debrief_payload,
    assign_prep_ordinals,
    badge_phase,
    compute_badge,
    compute_steps,
    current_step_key,
    load_snapshots,
)

#: Faza jednej rozmowy: przed końcem, okno telefonu, po oknie bez debriefu,
#: z debriefem zamykającym rundę, odwołana.
PHASE_SCHEDULED = "scheduled"
PHASE_CALL_DUE = "call_due"
PHASE_DEBRIEF_OVERDUE = "debrief_overdue"
PHASE_DEBRIEFED = "debriefed"
PHASE_CANCELLED = "cancelled"
INTERVIEW_PHASES = (
    PHASE_SCHEDULED,
    PHASE_CALL_DUE,
    PHASE_DEBRIEF_OVERDUE,
    PHASE_DEBRIEFED,
    PHASE_CANCELLED,
)

# Migawka „debrief jest” dla ``compute_steps`` jednej rozmowy — kroki czytają
# tylko obecność debriefu, nie jego treść.
_CLOSED_DEBRIEF = DebriefRef(
    id=0,
    overall_impression=None,
    offer_acceptance=None,
    acceptance_condition=None,
    candidate_questions=None,
    client_questions=None,
)


def aware(value: Optional[datetime]) -> Optional[datetime]:
    """Czas bez strefy z parametru zapytania = UTC (opis w specyfikacji)."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def call_window_minutes() -> int:
    return settings.POST_INTERVIEW_CALL_WINDOW_MINUTES


# ── Lista i jedna rozmowa ────────────────────────────────────────────────────


@dataclass(frozen=True)
class InterviewFilters:
    job_id: Optional[int] = None
    candidate_id: Optional[int] = None
    start_from: Optional[datetime] = None
    start_to: Optional[datetime] = None
    statuses: tuple[EventStatus, ...] = ()


def _visible_job_ids():
    # Ta sama podstawa co rejestr rekrutacji i reszta v1 — import w funkcji,
    # bo ``api.jobs`` ciągnie za sobą pół aplikacji.
    from app.api.jobs import jobs_register_base_clause

    return select(Job.id).where(jobs_register_base_clause())


def base_conditions() -> list[ColumnElement]:
    """Rozmowa kandydata u klienta w widocznej rekrutacji, kandydat istnieje."""
    return [
        CalendarEvent.event_type == EventType.client_interview,
        CalendarEvent.candidate_id.is_not(None),
        CalendarEvent.job_id.in_(_visible_job_ids()),
    ]


def interview_conditions(filters: InterviewFilters) -> list[ColumnElement]:
    conditions = base_conditions()
    if filters.job_id is not None:
        conditions.append(CalendarEvent.job_id == filters.job_id)
    if filters.candidate_id is not None:
        conditions.append(CalendarEvent.candidate_id == filters.candidate_id)
    if filters.start_from is not None:
        conditions.append(CalendarEvent.start_time >= aware(filters.start_from))
    if filters.start_to is not None:
        conditions.append(CalendarEvent.start_time < aware(filters.start_to))
    if filters.statuses:
        conditions.append(CalendarEvent.status.in_(filters.statuses))
    return conditions


def _interview_select():
    return (
        select(
            CalendarEvent.id,
            CalendarEvent.status,
            CalendarEvent.start_time,
            CalendarEvent.end_time,
            CalendarEvent.candidate_id,
            CalendarEvent.job_id,
            CalendarEvent.updated_at,
            Candidate.name.label("candidate_first_name"),
            Candidate.lastname.label("candidate_last_name"),
            Job.title.label("job_title"),
            Job.client_id,
            client_display_name_expression().label("client_name"),
        )
        .join(Candidate, Candidate.id == CalendarEvent.candidate_id)
        .join(Job, Job.id == CalendarEvent.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
    )


async def list_interview_rows(
    db: AsyncSession, filters: InterviewFilters, *, page: int, page_size: int
) -> tuple[list[Any], int]:
    conditions = interview_conditions(filters)
    total = (
        await db.scalar(
            select(func.count()).select_from(CalendarEvent).where(*conditions)
        )
    ) or 0
    rows = (
        await db.execute(
            _interview_select()
            .where(*conditions)
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return list(rows), int(total)


async def load_interview_row(db: AsyncSession, event_id: int) -> Optional[Any]:
    return (
        await db.execute(
            _interview_select().where(CalendarEvent.id == event_id, *base_conditions())
        )
    ).first()


# ── Faza rozmowy i cykl pary ─────────────────────────────────────────────────


def _status_value(status: Any) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def event_phase(
    *,
    status: str,
    start: datetime,
    end: Optional[datetime],
    debriefed: bool,
    now: datetime,
    call_window: int,
) -> str:
    """Faza JEDNEJ rozmowy liczona krokami cyklu (``compute_steps``).

    Migawka zawiera tylko tę rozmowę, więc kroki „Rozmowa”, „Telefon”
    i „Debrief” mówią o niej, a nie o rundzie, którą para prowadzi teraz
    (ta jest w ``cycle``).
    """
    if status == EventStatus.cancelled.value:
        return PHASE_CANCELLED
    snapshot = PairSnapshot(
        candidate_id=0,
        job_id=0,
        interview=EventRef(
            id=0,
            start=_utc(start),
            end=_utc(end) if end is not None else None,
            title="",
            status=status,
        ),
        debrief=_CLOSED_DEBRIEF if debriefed else None,
    )
    steps = {
        step["key"]: step["state"]
        for step in compute_steps(snapshot, now, call_window_minutes=call_window)
    }
    if steps["debrief"] == "done":
        return PHASE_DEBRIEFED
    if steps["interview"] == "scheduled":
        return PHASE_SCHEDULED
    if steps["call"] == "current":
        return PHASE_CALL_DUE
    return PHASE_DEBRIEF_OVERDUE


@dataclass(frozen=True)
class PairCycle:
    """Cykl pary tak, jak go widzi Tablica i ekran „Rozmowy u klienta”."""

    phase: Optional[str]
    current_step: Optional[str]
    slot_request_status: Optional[str]
    interview_event_id: Optional[int]
    # Rozmowy, które cykl teraz prowadzi: runda do debriefu i runda do prepów.
    round_event_ids: frozenset[int]


EMPTY_CYCLE = PairCycle(None, None, None, None, frozenset())


def cycle_of(snapshot: PairSnapshot, now: datetime, *, call_window: int) -> PairCycle:
    steps = compute_steps(snapshot, now, call_window_minutes=call_window)
    phase, _date = badge_phase(
        snapshot, compute_badge(snapshot, now, call_window_minutes=call_window)
    )
    rounds = {
        ev.id for ev in (snapshot.interview, snapshot.prep_interview) if ev is not None
    }
    return PairCycle(
        phase=phase,
        current_step=current_step_key(steps),
        slot_request_status=(
            snapshot.slot_request.status if snapshot.slot_request else None
        ),
        interview_event_id=snapshot.interview.id if snapshot.interview else None,
        round_event_ids=frozenset(rounds),
    )


async def pair_cycles(
    db: AsyncSession, pairs: Sequence[tuple[int, int]], *, now: datetime
) -> dict[tuple[int, int], PairCycle]:
    """Cykle par paczkami po ``MAX_PAIRS`` (``load_snapshots`` więcej nie bierze),
    w oknie plakietki Tablicy (14 dni wstecz, 90 do przodu)."""
    keys = sorted(set(pairs))
    window_start = now - timedelta(days=DEFAULT_DAYS_BACK)
    window_end = now + timedelta(days=BADGE_DAYS_AHEAD)
    call_window = call_window_minutes()
    out: dict[tuple[int, int], PairCycle] = {}
    for offset in range(0, len(keys), MAX_PAIRS):
        snaps = await load_snapshots(
            db,
            keys[offset : offset + MAX_PAIRS],
            window_start=window_start,
            window_end=window_end,
            now=now,
        )
        for key, snap in snaps.items():
            out[key] = cycle_of(snap, now, call_window=call_window)
    return out


async def closed_debrief_event_ids(
    db: AsyncSession, events: Sequence[tuple[int, datetime]]
) -> set[int]:
    """Rozmowy, których debrief zamyka rundę (ta sama reguła co bramka ruchu)."""
    starts = {event_id: start for event_id, start in events}
    if not starts:
        return set()
    rows = (
        await db.execute(
            select(
                InterviewFeedback.calendar_event_id,
                InterviewFeedback.client_questions,
                InterviewFeedback.no_client_questions,
                InterviewFeedback.updated_at,
            ).where(
                InterviewFeedback.calendar_event_id.in_(list(starts)),
                InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
            )
        )
    ).all()
    return {
        row.calendar_event_id
        for row in rows
        if debrief_closes_round(
            row.client_questions,
            row.no_client_questions,
            _utc(row.updated_at) if row.updated_at else None,
            _utc(starts[row.calendar_event_id]),
        )
    }


def interview_out(
    row: Any, *, now: datetime, debriefed: bool, cycle: PairCycle
) -> dict[str, Any]:
    status = _status_value(row.status)
    start = _utc(row.start_time)
    return {
        "event_id": row.id,
        "status": status,
        "start": start,
        "end": _utc(row.end_time) if row.end_time else None,
        "started": start <= now,
        "phase": event_phase(
            status=status,
            start=start,
            end=row.end_time,
            debriefed=debriefed,
            now=now,
            call_window=call_window_minutes(),
        ),
        "debrief_done": debriefed,
        "current_round": row.id in cycle.round_event_ids,
        "candidate_id": row.candidate_id,
        "candidate_first_name": row.candidate_first_name,
        "candidate_last_name": row.candidate_last_name,
        "job_id": row.job_id,
        "job_title": row.job_title,
        "client_id": row.client_id,
        "client_name": row.client_name,
        "cycle": {
            "phase": cycle.phase,
            "current_step": cycle.current_step,
            "slot_request_status": cycle.slot_request_status,
            "interview_event_id": cycle.interview_event_id,
        },
        "updated_at": row.updated_at,
    }


async def interviews_out(
    db: AsyncSession, rows: Sequence[Any], *, now: datetime
) -> list[dict[str, Any]]:
    """Strona rozmów: debriefy i cykle par hurtem (stała liczba zapytań)."""
    closed = await closed_debrief_event_ids(
        db, [(row.id, row.start_time) for row in rows]
    )
    cycles = await pair_cycles(
        db, [(row.candidate_id, row.job_id) for row in rows], now=now
    )
    return [
        interview_out(
            row,
            now=now,
            debriefed=row.id in closed,
            cycle=cycles.get((row.candidate_id, row.job_id), EMPTY_CYCLE),
        )
        for row in rows
    ]


# ── Prepy jednej rozmowy ─────────────────────────────────────────────────────


def split_round_preps(
    interviews: Sequence[tuple[int, datetime]],
    preps: Sequence[EventRef],
    event_id: int,
    now: datetime,
) -> tuple[list[EventRef], list[EventRef]]:
    """``(prepy rundy, prepy po rozmowie)`` dla rozmowy ``event_id``.

    ``interviews`` = nieodwołane rozmowy pary rosnąco po starcie. Lustro
    ``load_snapshots``: prep należy do rozmowy, przed którą wypada (a po
    poprzedniej); prep po OSTATNIEJ rozmowie, która jest jeszcze przed nami,
    to jej spóźniony prep. Numeracja jak na ekranie: prepy rundy osobno,
    spóźnione razem z nimi.
    """
    ids = [iid for iid, _start in interviews]
    if event_id not in ids:
        return [], []
    index = ids.index(event_id)
    iv_start = _utc(interviews[index][1])
    prev_start = _utc(interviews[index - 1][1]) if index > 0 else None
    on_time = [
        p
        for p in preps
        if p.start <= iv_start and (prev_start is None or p.start > prev_start)
    ]
    late: list[EventRef] = []
    if index == len(ids) - 1 and iv_start > now:
        late = [p for p in preps if p.start > iv_start]
    late_ids = {p.id for p in late}
    late_numbered = [
        p for p in assign_prep_ordinals([*on_time, *late]) if p.id in late_ids
    ]
    return assign_prep_ordinals(on_time), late_numbered


def prep_out(prep: EventRef, *, late: bool) -> dict[str, Any]:
    return {
        "event_id": prep.id,
        "prep_no": prep.prep_no if prep.prep_no is not None else prep.ordinal,
        "start": prep.start,
        "end": prep.end,
        "status": prep.status,
        "from_nexus": prep.prep_no is not None,
        "transcription_setup": prep.transcription_setup,
        "transcript_status": prep.transcript_status,
        "review_status": prep.review_status,
        "review_level": prep.review_level,
        "late": late,
    }


async def round_preps(
    db: AsyncSession, *, row: Any, now: datetime
) -> list[dict[str, Any]]:
    """Prepy rozmowy ``row`` (bez odwołanych) ze stanem transkryptu i oceny."""
    if _status_value(row.status) == EventStatus.cancelled.value:
        return []
    pair = (
        CalendarEvent.candidate_id == row.candidate_id,
        CalendarEvent.job_id == row.job_id,
        CalendarEvent.status != EventStatus.cancelled,
    )
    interviews = (
        await db.execute(
            select(CalendarEvent.id, CalendarEvent.start_time)
            .where(*pair, CalendarEvent.event_type == EventType.client_interview)
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
        )
    ).all()
    prep_rows = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.start_time,
                CalendarEvent.end_time,
                CalendarEvent.status,
                PrepMeeting.prep_no,
                PrepMeeting.transcription_setup,
                PrepMeeting.transcript_status,
                PrepReview.status.label("review_status"),
                PrepReview.level.label("review_level"),
            )
            .outerjoin(PrepMeeting, PrepMeeting.calendar_event_id == CalendarEvent.id)
            .outerjoin(PrepReview, PrepReview.prep_meeting_id == PrepMeeting.id)
            .where(*pair, CalendarEvent.event_type == EventType.prep_call)
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
        )
    ).all()
    preps = [
        EventRef(
            id=p.id,
            start=_utc(p.start_time),
            end=_utc(p.end_time) if p.end_time else None,
            title="",
            status=_status_value(p.status),
            prep_no=p.prep_no,
            transcription_setup=p.transcription_setup,
            transcript_status=p.transcript_status,
            review_status=p.review_status,
            review_level=p.review_level,
        )
        for p in prep_rows
    ]
    on_time, late = split_round_preps(
        [(i.id, i.start_time) for i in interviews], preps, row.id, now
    )
    return [prep_out(p, late=False) for p in on_time] + [
        prep_out(p, late=True) for p in late
    ]


# ── Debrief ──────────────────────────────────────────────────────────────────


async def load_debrief(db: AsyncSession, event_id: int) -> Optional[InterviewFeedback]:
    return await db.scalar(
        select(InterviewFeedback).where(
            InterviewFeedback.calendar_event_id == event_id,
            InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
        )
    )


def debrief_out(
    feedback: Any, *, start: datetime, notes: bool, costs: bool
) -> dict[str, Any]:
    """Debrief rozmowy: flagi zawsze, treść z ``notes``, warunek z ``notes``
    i ``costs`` (``amounts:read``). Wynik i liczba pytań — jak w doku osoby
    (``interview_cycle._debrief_payload``)."""
    summary = _debrief_payload(
        DebriefRef(
            id=feedback.id,
            overall_impression=feedback.overall_impression,
            offer_acceptance=feedback.offer_acceptance,
            acceptance_condition=feedback.acceptance_condition,
            candidate_questions=feedback.candidate_questions,
            client_questions=feedback.client_questions,
            concerns=feedback.concerns,
            no_client_questions=bool(feedback.no_client_questions),
        )
    )
    saved_at = _utc(feedback.updated_at) if feedback.updated_at else None
    questions = [
        line.strip()
        for line in (feedback.client_questions or "").splitlines()
        if line.strip()
    ]
    condition = (feedback.acceptance_condition or "").strip() or None
    return {
        "done": debrief_closes_round(
            feedback.client_questions,
            feedback.no_client_questions,
            saved_at,
            _utc(start),
        ),
        "saved_at": saved_at,
        "outcome": summary["outcome"],
        "offer_acceptance": summary["offer_acceptance"],
        "client_questions_count": summary["questions_count"],
        "no_client_questions": summary["no_client_questions"],
        "has_acceptance_condition": condition is not None,
        "notes_redacted": not notes,
        "candidate_comment": summary["candidate_comment"] if notes else None,
        "client_questions": questions if notes else None,
        "costs_redacted": not costs,
        "acceptance_condition": condition if notes and costs else None,
    }
