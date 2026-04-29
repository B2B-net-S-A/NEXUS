"""Auto-complete zaplanowanych interview po przekroczeniu end_time.

Wywoływane z `run_all_triggers()` przed 3 post-interview triggerami, żeby
zapewnić że eventy, które się skończyły, mają `status=completed` (warunek
triggerów T+15 / T+45 / T+2h).

Bezpieczeństwo:
- Flipujemy tylko `event_type=interview` — nie tkniemy meeting/deadline/prep_call
- Tylko `status=scheduled` (nie nadpisujemy cancelled)
- Tylko z ustawionym `end_time` (all-day eventy bez end pomijamy)
- Tylko gdy `end_time + grace_minutes < now` — daje czas na ręczne oznaczenie
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType

logger = logging.getLogger(__name__)


async def mark_ended_interviews_completed(db: AsyncSession, now: datetime) -> int:
    """Promote ended interview events from scheduled → completed.

    Returns the number of rows affected.
    """
    grace = timedelta(minutes=settings.INTERVIEW_AUTO_COMPLETE_GRACE_MINUTES)
    threshold = now.astimezone(timezone.utc) - grace

    stmt = (
        update(CalendarEvent)
        .where(
            CalendarEvent.event_type == EventType.interview,
            CalendarEvent.status == EventStatus.scheduled,
            CalendarEvent.end_time.isnot(None),
            CalendarEvent.end_time < threshold,
        )
        .values(status=EventStatus.completed)
        .execution_options(synchronize_session=False)
    )
    result = await db.execute(stmt)
    count = result.rowcount or 0
    if count:
        logger.info(
            "calendar_auto_complete: promoted %d interview(s) to completed", count
        )
    return count
