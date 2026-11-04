"""Rozmowa u klienta wpisana bez „Terminów od klienta” (20.10.2026).

Wydarzenie ``client_interview`` zakładała dotąd tylko ścieżka wniosku
o terminy (``interview_slots.confirm``). Zespół jej nie używa: w 30 dniach
88 z 99 par weszło w etap „Rozmowa z klientem” bez wydarzenia, więc nie było
telefonu po rozmowie, zadania „Uzupełnij debrief” ani bramki przed „Umową” —
pytania klienta lądowały w notatkach.

Dwie drogi zakładają tu wydarzenie:

* przesunięcie karty na „Rozmowa z klientem” z odpowiedzią na „Kiedy
  rozmowa?” (``POST /api/interview-cycle/client-interviews``) — dalej działa
  cały istniejący cykl (telefon ≤30 min, debrief, bramka);
* zapis pytań bez terminu (``PUT /api/interview-cycle/pairs/{c}/{j}/debrief``)
  — „Kiedy była rozmowa?” zakłada odbytą rozmowę i debrief trafia pod nią.

Wydarzenie jest tylko w NEXUSIE (bez Outlooka): kandydata zaprasza klient.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.services import interview_slots

DEFAULT_DURATION_MINUTES = 60
MIN_DURATION_MINUTES = 15
MAX_DURATION_MINUTES = 240
# Termin wpisany przy przesunięciu: rozmowa sprzed tygodnia to jeszcze
# „przesuwam po fakcie”, dalej to pomyłka w dacie.
MAX_DAYS_BACK = 30
MAX_DAYS_AHEAD = 120
# Godzina, gdy przy zapisie pytań nikt nie pamięta, o której była rozmowa.
DEFAULT_HELD_AT = time(9, 0)


def _tz() -> ZoneInfo:
    return ZoneInfo(settings.BUSINESS_TZ)


def held_interview_start(
    held_on: date, held_at: Optional[time], *, now: datetime
) -> datetime:
    """Start odbytej rozmowy z „Kiedy była rozmowa?” (dzień + opcjonalna godzina,
    czas firmy). Bez godziny: 9:00, a dziś przed 9:00 — chwila temu. Przyszłość
    = 422, bo debrief zapisuje rozmowę, która już była."""
    tz = _tz()
    local_now = now.astimezone(tz)
    if held_on > local_now.date():
        raise HTTPException(
            status_code=422, detail="Data rozmowy nie może być w przyszłości."
        )
    if held_on < local_now.date() - timedelta(days=MAX_DAYS_BACK * 6):
        raise HTTPException(
            status_code=422, detail="Sprawdź datę rozmowy — jest sprzed pół roku."
        )
    start = datetime.combine(held_on, held_at or DEFAULT_HELD_AT, tzinfo=tz)
    if start > local_now:
        if held_at is not None:
            raise HTTPException(
                status_code=422,
                detail="Godzina rozmowy jeszcze nie minęła — debrief zapiszesz po rozmowie.",
            )
        start = local_now - timedelta(minutes=1)
    return start.astimezone(timezone.utc)


def validate_planned_start(start: datetime, *, now: datetime) -> datetime:
    """Termin z okna przesunięcia: najwyżej ``MAX_DAYS_BACK`` dni wstecz
    (karta przesuwana po rozmowie) i ``MAX_DAYS_AHEAD`` naprzód."""
    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start < now - timedelta(days=MAX_DAYS_BACK):
        raise HTTPException(
            status_code=422,
            detail=f"Termin rozmowy może być najwyżej {MAX_DAYS_BACK} dni wstecz.",
        )
    if start > now + timedelta(days=MAX_DAYS_AHEAD):
        raise HTTPException(
            status_code=422, detail="Sprawdź datę rozmowy — jest za kilka miesięcy."
        )
    return start.astimezone(timezone.utc)


async def lock_pair(db: AsyncSession, *, candidate_id: int, job_id: int) -> None:
    """Dwa kliknięcia „Przesuń” / „Zapisz pytania” naraz nie założą dwóch rozmów."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"),
        {"key": f"client-interview:{candidate_id}:{job_id}"},
    )


async def upcoming_interview(
    db: AsyncSession, *, candidate_id: int, job_id: int, now: datetime
) -> Optional[CalendarEvent]:
    """Zaplanowana (przyszła, nieodwołana) rozmowa u klienta pary."""
    return await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job_id,
            CalendarEvent.event_type == EventType.client_interview,
            CalendarEvent.status != EventStatus.cancelled,
            CalendarEvent.start_time > now,
        )
        .order_by(CalendarEvent.start_time)
        .limit(1)
    )


async def held_interview_on(
    db: AsyncSession, *, candidate_id: int, job_id: int, day: date, now: datetime
) -> Optional[CalendarEvent]:
    """Odbyta (rozpoczęta, nieodwołana) rozmowa pary z danego dnia firmy."""
    tz = _tz()
    day_start = datetime.combine(day, time(0, 0), tzinfo=tz)
    return await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job_id,
            CalendarEvent.event_type == EventType.client_interview,
            CalendarEvent.status != EventStatus.cancelled,
            CalendarEvent.start_time >= day_start,
            CalendarEvent.start_time < day_start + timedelta(days=1),
            CalendarEvent.start_time <= now,
        )
        .order_by(CalendarEvent.start_time.desc())
        .limit(1)
    )


async def create_interview(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    start: datetime,
    duration_minutes: int,
    created_by: int,
    held: bool,
    now: datetime,
) -> CalendarEvent:
    """Wydarzenie ``client_interview`` pary — właściciel to rekruter kandydata
    (ta sama reguła co wniosek o terminy), bez niego wpisujący."""
    job = await db.get(Job, job_id)
    candidate = await db.get(Candidate, candidate_id)
    if job is None or candidate is None:
        raise HTTPException(
            status_code=404, detail="Nie znaleziono kandydata albo rekrutacji."
        )
    owner = (
        await interview_slots.default_recruiter_id(
            db, candidate_id=candidate_id, job_id=job_id
        )
        or created_by
    )
    end = start + timedelta(minutes=duration_minutes)
    event = CalendarEvent(
        title=interview_slots._interview_title(candidate, job),
        event_type=EventType.client_interview,
        start_time=start,
        end_time=end,
        all_day=False,
        status=EventStatus.completed if held or end <= now else EventStatus.scheduled,
        external_source="manual",
        created_by=created_by,
        attendees=[],
        candidate_id=candidate_id,
        job_id=job_id,
        client_id=job.client_id,
        operational_owner_id=owner,
        reminder_minutes=15,
        description=(
            "Rozmowa kandydata u klienta — termin wpisany w NEXUSIE "
            + ("razem z pytaniami po rozmowie." if held else "przy przesunięciu karty.")
        ),
    )
    db.add(event)
    await db.flush()
    return event
