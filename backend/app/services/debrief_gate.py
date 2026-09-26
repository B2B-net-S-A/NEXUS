"""Bramka „telefon po rozmowie u klienta” (pipeline v4, decyzja Artura 23.09.2026).

Po rozmowie u klienta rekruter dzwoni do kandydata (≤30 min) i pyta, o co
pytał klient. Te pytania zasilają bank pytań klienta: prep i prep 2 kolejnych
kandydatów oraz profil Championa tej i przyszłych rekrutacji u tego klienta.
Dlatego karta nie idzie dalej („Umowa”, „Zatrudniony”), dopóki debrief
NAJNOWSZEJ odbytej rozmowy nie ma pytań albo jawnego „klient nie zadawał
pytań”.

Rozmowa ZAPLANOWANA (termin jeszcze nie nadszedł) też blokuje ruch — do
23.09.2026 bramka patrzyła tylko na rozmowy odbyte, więc karta z rozmową jutro
przechodziła do „Umowy” bez debriefu. Debrief zapisany PRZED rozpoczęciem
rozmowy (``updated_at < start``) się nie liczy: po rozmowie, której jeszcze nie
było, nie ma czego raportować (zapis blokuje dziś ``PUT …/debrief``, ale takie
wiersze powstały, zanim ta blokada weszła).

Bramka dotyczy wyłącznie par, które mają rozmowę ``client_interview``
w kalendarzu NEXUSA. Proces prowadzony w Trafficie takiej rozmowy nie ma i nie
da się go tym zablokować — to świadome (brak wydarzenia = brak bramki).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback

DEBRIEF_REQUIRED_CODE = "DEBRIEF_REQUIRED"
DEBRIEF_REQUIRED_MESSAGE = (
    "Najpierw zadzwoń do kandydata po rozmowie i zapisz pytania klienta."
)


def interview_not_started_message(start: Optional[datetime]) -> str:
    """Komunikat dla rozmowy u klienta, która jeszcze się nie zaczęła."""
    if start is None:
        when = ""
    else:
        local = start.astimezone(ZoneInfo(settings.BUSINESS_TZ))
        when = f" (termin {local:%d.%m.%Y, %H:%M})"
    return (
        f"Rozmowa u klienta jeszcze się nie odbyła{when}. Debrief uzupełnisz po "
        "rozmowie — po telefonie do kandydata zapisz pytania klienta, dopiero "
        "wtedy kandydat przejdzie dalej."
    )


def debrief_saved_after_start(
    saved_at: Optional[datetime], start: Optional[datetime]
) -> bool:
    """Debrief liczy się tylko, gdy zapisano go po rozpoczęciu rozmowy."""
    if saved_at is None or start is None:
        return saved_at is not None
    return saved_at >= start


def debrief_is_complete(
    client_questions: Optional[str], no_client_questions: Optional[bool]
) -> bool:
    """Debrief spełnia bramkę: co najmniej jedno pytanie albo jawne „nie pytał”."""
    if no_client_questions:
        return True
    return any(line.strip() for line in (client_questions or "").splitlines())


def pick_current_round(
    rounds: Sequence[tuple[datetime, bool]], now: datetime
) -> Optional[int]:
    """Indeks BIEŻĄCEJ rundy rozmów u klienta pary albo ``None`` (brak rozmów).

    ``rounds`` = ``(start, debrief_zamknięty)`` posortowane rosnąco po starcie,
    bez odwołanych. Jedna reguła dla ekranu „Rozmowy u klienta”, plakietki
    Tablicy, kolejki prepów, bramki debriefu i planowania prepu:

    1. ostatnia rozmowa, która już się zaczęła, bez debriefu — telefon
       i debrief po niej są pilniejsze niż kolejna runda;
    2. inaczej najwcześniejsza rozmowa w przyszłości — to do niej robi się
       prepy;
    3. inaczej ostatnia odbyta (wszystko zamknięte).

    Runda 8 (R8-N9-3): od decyzji IC-1 (26.09.2026) para może mieć kilka
    zaplanowanych rund naraz. Dotąd „bieżąca” była najpóźniejsza rozmowa,
    także przyszła — telefon po rundzie, która właśnie się skończyła, znikał,
    a planowanie prepu i ekran liczyły rundę inaczej (409 przy zadaniu
    „Brak prepu”).
    """
    if not rounds:
        return None
    started = [i for i, (start, _closed) in enumerate(rounds) if start <= now]
    last_started = started[-1] if started else None
    if last_started is not None and not rounds[last_started][1]:
        return last_started
    upcoming = [i for i, (start, _closed) in enumerate(rounds) if start > now]
    if upcoming:
        return upcoming[0]
    return last_started


async def missing_debrief(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Zwraca szczegół odmowy 409, gdy brakuje debriefu po rozmowie u klienta.

    ``None`` = bramka nie dotyczy pary (brak rozmowy u klienta w kalendarzu
    poza odwołanymi) albo debrief BIEŻĄCEJ rundy (``pick_current_round``) jest
    kompletny i zapisany po jej rozpoczęciu. Bieżąca runda w przyszłości =
    odmowa z flagą ``interview_pending`` (debrief będzie możliwy po rozmowie).
    Jedno zapytanie.
    """
    now = now or datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.start_time,
                InterviewFeedback.client_questions,
                InterviewFeedback.no_client_questions,
                InterviewFeedback.updated_at,
            )
            .outerjoin(
                InterviewFeedback,
                and_(
                    InterviewFeedback.calendar_event_id == CalendarEvent.id,
                    InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
                ),
            )
            .where(
                CalendarEvent.candidate_id == candidate_id,
                CalendarEvent.job_id == job_id,
                CalendarEvent.event_type == EventType.client_interview,
                CalendarEvent.status != EventStatus.cancelled,
            )
            .order_by(CalendarEvent.start_time.asc(), CalendarEvent.id.asc())
        )
    ).all()
    if not rows:
        return None

    def _aware(value: Optional[datetime]) -> Optional[datetime]:
        if value is None or value.tzinfo is not None:
            return value
        return value.replace(tzinfo=timezone.utc)

    def _closed(row) -> bool:
        return debrief_is_complete(row[2], row[3]) and debrief_saved_after_start(
            _aware(row[4]), _aware(row[1])
        )

    # Runda 8 (R8-N9-3): ta sama „bieżąca runda” co ekran i planowanie prepu.
    index = pick_current_round([(_aware(r[1]) or now, _closed(r)) for r in rows], now)
    row = rows[index]
    event_id, event_start = row[0], _aware(row[1])
    pending = event_start is not None and event_start > now
    if not pending and _closed(row):
        return None
    return {
        "code": DEBRIEF_REQUIRED_CODE,
        "message": (
            interview_not_started_message(event_start)
            if pending
            else DEBRIEF_REQUIRED_MESSAGE
        ),
        "interview_pending": pending,
        "event_id": event_id,
        "event_start": event_start.isoformat() if event_start else None,
        "candidate_id": candidate_id,
        "job_id": job_id,
    }
