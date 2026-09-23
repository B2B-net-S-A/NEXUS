"""Bramka „telefon po rozmowie u klienta” (pipeline v4, decyzja Artura 23.09.2026).

Po rozmowie u klienta rekruter dzwoni do kandydata (≤30 min) i pyta, o co
pytał klient. Te pytania zasilają bank pytań klienta: prep i prep 2 kolejnych
kandydatów oraz profil Championa tej i przyszłych rekrutacji u tego klienta.
Dlatego karta nie idzie dalej („Umowa”, „Zatrudniony”), dopóki debrief
NAJNOWSZEJ odbytej rozmowy nie ma pytań albo jawnego „klient nie zadawał
pytań”.

Bramka dotyczy wyłącznie par, które mają rozmowę ``client_interview``
w kalendarzu NEXUSA. Proces prowadzony w Trafficie takiej rozmowy nie ma i nie
da się go tym zablokować — to świadome (brak wydarzenia = brak bramki).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback

DEBRIEF_REQUIRED_CODE = "DEBRIEF_REQUIRED"
DEBRIEF_REQUIRED_MESSAGE = (
    "Najpierw zadzwoń do kandydata po rozmowie i zapisz pytania klienta."
)


def debrief_is_complete(
    client_questions: Optional[str], no_client_questions: Optional[bool]
) -> bool:
    """Debrief spełnia bramkę: co najmniej jedno pytanie albo jawne „nie pytał”."""
    if no_client_questions:
        return True
    return any(line.strip() for line in (client_questions or "").splitlines())


async def missing_debrief(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Zwraca szczegół odmowy 409, gdy brakuje debriefu po rozmowie u klienta.

    ``None`` = bramka nie dotyczy pary (brak odbytej rozmowy u klienta w
    kalendarzu) albo debrief najnowszej rozmowy jest kompletny. Jedno zapytanie.
    """
    now = now or datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.start_time,
                InterviewFeedback.client_questions,
                InterviewFeedback.no_client_questions,
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
                CalendarEvent.start_time <= now,
            )
            .order_by(CalendarEvent.start_time.desc(), CalendarEvent.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    event_id, event_start, questions, no_questions = row
    if debrief_is_complete(questions, no_questions):
        return None
    return {
        "code": DEBRIEF_REQUIRED_CODE,
        "message": DEBRIEF_REQUIRED_MESSAGE,
        "event_id": event_id,
        "event_start": event_start.isoformat() if event_start else None,
        "candidate_id": candidate_id,
        "job_id": job_id,
    }
