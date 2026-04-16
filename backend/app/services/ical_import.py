"""
Phase 7b.6 — iCal URL calendar import.

Practical fallback for full Outlook/Google OAuth sync: users publish their
calendar as a public iCal URL (available in every major calendar app) and
paste that URL into Nexus. We pull events on demand and upsert them.

Strategy:
- Fetch iCal feed via httpx
- Parse with `icalendar`
- For each VEVENT: upsert CalendarEvent by (external_source, external_id=UID)
- Track counts and skip past events older than `since_days`
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus, EventType

logger = logging.getLogger(__name__)


@dataclass
class ICalImportResult:
    source_url: str
    events_fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped_past: int = 0
    errors: int = 0
    error_samples: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source_url": self.source_url,
            "events_fetched": self.events_fetched,
            "inserted": self.inserted,
            "updated": self.updated,
            "skipped_past": self.skipped_past,
            "errors": self.errors,
            "error_samples": self.error_samples[:20],
        }


def _to_datetime(v) -> Optional[datetime]:
    """iCal values may be datetime, date, or None; normalize to UTC datetime."""
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    if isinstance(v, date):
        return datetime(v.year, v.month, v.day, tzinfo=timezone.utc)
    return None


async def import_ical_url(
    db: AsyncSession,
    url: str,
    *,
    since_days: int = 7,
    source_tag: str = "ical",
    creator_id: Optional[int] = None,
) -> ICalImportResult:
    """Fetch iCal feed and upsert events into calendar_events."""
    from icalendar import Calendar  # local import keeps cold-start light

    result = ICalImportResult(source_url=url)
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(0, since_days))

    try:
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            raw = resp.content
    except Exception as e:  # noqa: BLE001
        logger.exception("iCal fetch failed")
        result.errors += 1
        result.error_samples.append(f"fetch: {e!r}")
        return result

    try:
        cal = Calendar.from_ical(raw)
    except Exception as e:  # noqa: BLE001
        result.errors += 1
        result.error_samples.append(f"parse: {e!r}")
        return result

    for component in cal.walk("VEVENT"):
        result.events_fetched += 1
        try:
            uid = str(component.get("UID") or "").strip()
            if not uid:
                result.errors += 1
                if len(result.error_samples) < 20:
                    result.error_samples.append("event missing UID")
                continue

            summary = str(component.get("SUMMARY") or "Spotkanie").strip()[:255]
            description = str(component.get("DESCRIPTION") or "") or None
            location = str(component.get("LOCATION") or "") or None

            dtstart = _to_datetime(getattr(component.get("DTSTART"), "dt", None))
            dtend = _to_datetime(getattr(component.get("DTEND"), "dt", None))

            if dtstart is None:
                result.errors += 1
                if len(result.error_samples) < 20:
                    result.error_samples.append(f"uid={uid}: missing DTSTART")
                continue

            # Skip past events older than cutoff
            if dtstart < cutoff:
                result.skipped_past += 1
                continue

            # Upsert by (external_source, external_id)
            existing = await db.scalar(
                select(CalendarEvent).where(
                    CalendarEvent.external_source == source_tag,
                    CalendarEvent.external_id == uid,
                )
            )
            if existing:
                existing.title = summary
                existing.description = description
                existing.location = location
                existing.start_time = dtstart
                existing.end_time = dtend
                result.updated += 1
            else:
                ev = CalendarEvent(
                    title=summary,
                    description=description,
                    event_type=EventType.meeting,
                    start_time=dtstart,
                    end_time=dtend,
                    all_day=False,
                    location=location,
                    status=EventStatus.scheduled,
                    external_source=source_tag,
                    external_id=uid,
                    created_by=creator_id,
                )
                db.add(ev)
                result.inserted += 1
        except Exception as e:  # noqa: BLE001
            result.errors += 1
            if len(result.error_samples) < 20:
                result.error_samples.append(f"event: {e!r}")

    try:
        await db.commit()
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        result.errors += 1
        result.error_samples.append(f"commit: {e!r}")

    return result
