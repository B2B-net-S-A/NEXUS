"""Calendar event creation via Graph.

Phase 1: one-shot `create_event` with candidate + extra attendees. Graph
auto-sends the invite.

Uses the existing `calendar_events` table with `external_source='microsoft365'`
and `external_id=<graph event id>` — same upsert pattern as `ical_import.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.m365 import M365Connection
from app.services.m365.graph_client import GraphClient
from app.services.m365.html_sanitize import sanitize_html

logger = logging.getLogger(__name__)

M365_SOURCE = "microsoft365"


async def create_event(
    db: AsyncSession,
    connection: M365Connection,
    *,
    candidate: Optional[Candidate],
    title: str,
    description: str,
    start: datetime,
    end: datetime,
    event_type: EventType = EventType.interview,
    extra_attendees: Optional[list[str]] = None,
    invite_candidate: bool = True,
) -> CalendarEvent:
    """Create a Graph event + matching local CalendarEvent row."""
    extras = list(extra_attendees or [])
    attendee_emails: list[str] = []
    if invite_candidate and candidate and candidate.email:
        attendee_emails.append(candidate.email)
    attendee_emails.extend(e for e in extras if e and e not in attendee_emails)

    body_html = sanitize_html(description or "")
    payload = {
        "subject": title,
        "body": {"contentType": "HTML", "content": body_html},
        "start": {"dateTime": start.isoformat(), "timeZone": settings.BUSINESS_TZ},
        "end": {"dateTime": end.isoformat(), "timeZone": settings.BUSINESS_TZ},
        "attendees": [
            {
                "emailAddress": {"address": a},
                "type": "required",
            }
            for a in attendee_emails
        ],
    }

    async with GraphClient(connection, db) as gc:
        event = await gc.post("/me/events", json=payload)

    graph_id = event["id"]
    change_key = event.get("changeKey")

    row = CalendarEvent(
        title=title[:255],
        description=description,
        event_type=event_type,
        start_time=start,
        end_time=end,
        all_day=False,
        attendees=[{"address": a} for a in attendee_emails],
        candidate_id=candidate.id if candidate else None,
        status=EventStatus.scheduled,
        external_source=M365_SOURCE,
        external_id=graph_id,
        created_by=connection.user_id,
        m365_change_key=change_key,
    )

    db.add(row)
    await db.flush()
    return row
