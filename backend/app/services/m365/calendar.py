"""Calendar event creation via Graph.

Phase 1: one-shot `create_event` with candidate + extra attendees. Graph
auto-sends the invite.

Uses the existing `calendar_events` table with `external_source='microsoft365'`
and `external_id=<graph event id>` — same upsert pattern as `ical_import.py`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.m365 import M365Connection
from app.services.m365.graph_client import GraphClient
from app.services.m365.html_sanitize import sanitize_html

logger = logging.getLogger(__name__)

M365_SOURCE = "microsoft365"

FreeBusyStatus = Literal[
    "free", "tentative", "busy", "oof", "workingElsewhere", "unknown"
]

# Graph `availabilityView` digit → status name. The string is a sequence of
# single-digit codes, one per `availabilityViewInterval`-minute slot, e.g.
# "002200" for two free, two busy, two free in 30-min granularity.
# Reference: https://learn.microsoft.com/en-us/graph/api/calendar-getschedule
_AVAILABILITY_DIGITS: dict[str, FreeBusyStatus] = {
    "0": "free",
    "1": "tentative",
    "2": "busy",
    "3": "oof",
    "4": "workingElsewhere",
}


class FreeBusySlot(TypedDict):
    start: datetime
    end: datetime
    status: FreeBusyStatus


# Graph `getSchedule` supports up to 20 schedules per call.
_MAX_SCHEDULES = 20
# Granularity floor enforced by Graph (5 min). We default to 30 — sufficient
# for a typical 30/45/60-min interview slot and keeps the response compact.
_DEFAULT_INTERVAL_MINUTES = 30


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


# ── Free-busy lookup ────────────────────────────────────────────────────────


def _parse_iso_utc(value: str) -> datetime:
    """Parse a Graph dateTime string and normalize to UTC.

    Graph returns naive ISO strings (no `Z`/offset) and a separate `timeZone`
    field. Our caller always asks for `UTC`, so a missing tz is treated as UTC.
    """
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _slots_from_schedule_items(
    schedule_items: list[dict],
) -> list[FreeBusySlot]:
    out: list[FreeBusySlot] = []
    for item in schedule_items:
        try:
            start = _parse_iso_utc(item["start"]["dateTime"])
            end = _parse_iso_utc(item["end"]["dateTime"])
        except (KeyError, TypeError, ValueError):
            continue
        raw_status = (item.get("status") or "unknown").strip()
        # Graph sometimes returns lower-case ("busy") sometimes camel
        # ("workingElsewhere") — normalize to the typed Literal we expose.
        status: FreeBusyStatus = (
            raw_status if raw_status in _AVAILABILITY_DIGITS.values() else "unknown"
        )
        out.append({"start": start, "end": end, "status": status})
    return out


def _slots_from_availability_view(
    view: str, window_start: datetime, interval_minutes: int
) -> list[FreeBusySlot]:
    """Decode the `availabilityView` digit string into per-slot rows.

    Each char maps to one `interval_minutes` slot starting at `window_start`.
    Unknown digits become `unknown` — Graph occasionally emits non-mapped
    codes (e.g. for "no data" tenants) and we should not pretend they're free.
    """
    out: list[FreeBusySlot] = []
    for idx, ch in enumerate(view):
        slot_start = window_start + timedelta(minutes=interval_minutes * idx)
        slot_end = slot_start + timedelta(minutes=interval_minutes)
        out.append(
            {
                "start": slot_start,
                "end": slot_end,
                "status": _AVAILABILITY_DIGITS.get(ch, "unknown"),
            }
        )
    return out


def parse_free_busy_response(
    payload: dict,
    *,
    window_start: datetime,
    interval_minutes: int,
) -> dict[str, list[FreeBusySlot]]:
    """Turn a Graph `getSchedule` payload into `{email: [slots]}`.

    Prefers `scheduleItems` (exact start/end) and falls back to
    `availabilityView` (uniform digit string) when items are absent —
    Graph may return only the view for low-fidelity tenants. If a schedule
    carries an `error`, we surface it as a single `unknown` slot covering
    the whole requested window so the UI can decide to stay silent rather
    than display a confusing partial result.
    """
    schedules: list[dict] = payload.get("value", []) or []
    out: dict[str, list[FreeBusySlot]] = {}
    for sched in schedules:
        email = (sched.get("scheduleId") or "").strip()
        if not email:
            continue
        if sched.get("error"):
            window_end = window_start + timedelta(
                minutes=interval_minutes
                * max(1, len(sched.get("availabilityView") or ""))
            )
            out[email] = [
                {"start": window_start, "end": window_end, "status": "unknown"}
            ]
            continue
        items = sched.get("scheduleItems") or []
        if items:
            out[email] = _slots_from_schedule_items(items)
        else:
            view = sched.get("availabilityView") or ""
            out[email] = _slots_from_availability_view(
                view, window_start, interval_minutes
            )
    return out


async def get_free_busy(
    gc: GraphClient,
    attendees: list[str],
    start: datetime,
    end: datetime,
    *,
    interval_minutes: int = _DEFAULT_INTERVAL_MINUTES,
) -> dict[str, list[FreeBusySlot]]:
    """Query Graph `getSchedule` for the given attendees and time window.

    `start`/`end` MUST be timezone-aware. The Graph payload echoes back the
    requested timezone, so we always ask for UTC and convert client-supplied
    datetimes to UTC before sending — keeps the parser dead simple.

    Returns `{email: [slots]}` where each slot is a contiguous busy/tentative/
    etc. block. Free time between slots is omitted (caller infers gaps).
    Attendees with no Outlook calendar visible to this tenant return a single
    `unknown` slot covering the requested window.
    """
    if not attendees:
        return {}
    if len(attendees) > _MAX_SCHEDULES:
        raise ValueError(
            f"Graph getSchedule allows at most {_MAX_SCHEDULES} schedules per call"
        )
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start/end must be timezone-aware")
    if end <= start:
        raise ValueError("end must be after start")

    start_utc = start.astimezone(timezone.utc)
    end_utc = end.astimezone(timezone.utc)
    payload = {
        "schedules": list(attendees),
        "startTime": {"dateTime": start_utc.isoformat(), "timeZone": "UTC"},
        "endTime": {"dateTime": end_utc.isoformat(), "timeZone": "UTC"},
        "availabilityViewInterval": interval_minutes,
    }
    response = await gc.post("/me/calendar/getSchedule", json=payload)
    return parse_free_busy_response(
        response, window_start=start_utc, interval_minutes=interval_minutes
    )
