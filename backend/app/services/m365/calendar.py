"""Calendar event creation via Graph.

Phase 1: one-shot `create_event` with candidate + extra attendees. Graph
auto-sends the invite.

Uses the existing `calendar_events` table with `external_source='microsoft365'`
and `external_id=<graph event id>` — same upsert pattern as `ical_import.py`.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.m365 import M365Connection
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.m365.html_sanitize import sanitize_html

logger = logging.getLogger(__name__)

M365_SOURCE = "microsoft365"

# Event types that default to including a Teams online-meeting link. Other
# types (deadline, generic meeting) skip the meeting unless the
# caller asks explicitly. Keeping the set narrow avoids spamming users with
# join URLs for events they never intended to hold over Teams.
_TEAMS_DEFAULT_EVENT_TYPES: frozenset[EventType] = frozenset(
    # 0338: prep z kandydatem przed rozmową u klienta to call na Teams.
    {EventType.interview, EventType.screening, EventType.prep_call}
)

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


def _graph_datetime(value: datetime) -> dict:
    """`{dateTime, timeZone}` dla Grapha: czas LOKALNY strefy biznesowej.

    Graph czyta `dateTime` jako czas w podanej `timeZone`; ISO z przesunięciem
    (`…+00:00`) przy `timeZone=Europe/Warsaw` to niejednoznaczność, którą
    lepiej rozstrzygnąć po naszej stronie. Naiwny czas traktujemy jak UTC
    (tak zapisuje go reszta NEXUSA).
    """
    from zoneinfo import ZoneInfo

    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    local = aware.astimezone(ZoneInfo(settings.BUSINESS_TZ)).replace(tzinfo=None)
    return {"dateTime": local.isoformat(), "timeZone": settings.BUSINESS_TZ}


def _resolve_with_teams(
    with_teams_meeting: Optional[bool], event_type: EventType
) -> bool:
    """Decide whether to ask Graph for a Teams meeting on this event."""
    if with_teams_meeting is not None:
        return with_teams_meeting
    return event_type in _TEAMS_DEFAULT_EVENT_TYPES


def event_transaction_id(
    *,
    owner_user_id: Optional[int],
    title: str,
    start: datetime,
    end: datetime,
    attendee_emails: list[str],
    intent_id: Optional[str] = None,
) -> str:
    """Stały ``transactionId`` intencji utworzenia wydarzenia (INT-06).

    Graph rozpoznaje po nim powtórzone ``POST /me/events`` i nie tworzy
    drugiego spotkania ani drugiego zaproszenia. Wartość MUSI być taka sama
    przy każdym ponowieniu tej samej operacji — dlatego nie jest losowa:
    jawny identyfikator intencji wołającego albo skrót właściciela, tytułu,
    terminu i uczestników.
    """
    if intent_id:
        seed = f"intent|{intent_id}"
    else:
        seed = "|".join(
            [
                "event",
                str(owner_user_id or ""),
                (title or "").strip(),
                start.isoformat(),
                end.isoformat(),
                ",".join(sorted({a.strip().lower() for a in attendee_emails if a})),
            ]
        )
    return "nexus-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:40]


def _build_event_payload(
    *,
    title: str,
    description: str,
    start: datetime,
    end: datetime,
    attendee_emails: list[str],
    want_teams: bool,
    transaction_id: Optional[str] = None,
) -> dict:
    """Shape a Graph `/me/events` POST body.

    Pure function — extracted from `create_event` so the payload contract
    (especially the conditional `isOnlineMeeting` block) is unit-testable
    without standing up a Graph mock or DB session.
    """
    body_html = sanitize_html(description or "")
    payload: dict = {
        "subject": title,
        "body": {"contentType": "HTML", "content": body_html},
        "start": _graph_datetime(start),
        "end": _graph_datetime(end),
        "attendees": [
            {
                "emailAddress": {"address": a},
                "type": "required",
            }
            for a in attendee_emails
        ],
    }
    if want_teams:
        payload["isOnlineMeeting"] = True
        payload["onlineMeetingProvider"] = "teamsForBusiness"
    if transaction_id:
        payload["transactionId"] = transaction_id
    return payload


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
    with_teams_meeting: Optional[bool] = None,
    intent_id: Optional[str] = None,
) -> CalendarEvent:
    """Create a Graph event + matching local CalendarEvent row.

    ``intent_id`` — opcjonalny stały identyfikator operacji wołającego; z niego
    (albo z treści wydarzenia) powstaje ``transactionId``, dzięki któremu Graph
    nie tworzy duplikatu przy powtórzonym żądaniu (INT-06).

    When `with_teams_meeting` is True, Graph generates a Teams join URL and
    embeds it in the event invitation. When None (default), the helper opts
    interview/screening events in automatically and leaves the rest opt-out.
    """
    extras = list(extra_attendees or [])
    attendee_emails: list[str] = []
    if invite_candidate and candidate and candidate.email:
        attendee_emails.append(candidate.email)
    attendee_emails.extend(e for e in extras if e and e not in attendee_emails)

    want_teams = _resolve_with_teams(with_teams_meeting, event_type)
    payload = _build_event_payload(
        title=title,
        description=description,
        start=start,
        end=end,
        attendee_emails=attendee_emails,
        want_teams=want_teams,
        transaction_id=event_transaction_id(
            owner_user_id=connection.user_id,
            title=title,
            start=start,
            end=end,
            attendee_emails=attendee_emails,
            intent_id=intent_id,
        ),
    )

    async with GraphClient(connection, db) as gc:
        event = await gc.post("/me/events", json=payload)

    graph_id = event["id"]
    change_key = event.get("changeKey")
    online_meeting = event.get("onlineMeeting") or {}
    join_url = (
        online_meeting.get("joinUrl") if isinstance(online_meeting, dict) else None
    )

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
        online_meeting_url=join_url,
    )

    db.add(row)
    await db.flush()
    return row


# ── Update ──────────────────────────────────────────────────────────────────


def build_update_payload(
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    location: Optional[str] = None,
    set_location: bool = False,
) -> dict:
    """Częściowe ciało `PATCH /me/events/{id}` — tylko pola, które się zmieniły.

    Czysta funkcja, żeby kontrakt (strefa czasowa, HTML opisu, zerowanie
    miejsca) dało się sprawdzić bez Grapha.
    """
    payload: dict = {}
    if title is not None:
        payload["subject"] = title
    if description is not None:
        payload["body"] = {"contentType": "HTML", "content": sanitize_html(description)}
    if start is not None:
        payload["start"] = _graph_datetime(start)
    if end is not None:
        payload["end"] = _graph_datetime(end)
    if set_location:
        payload["location"] = {"displayName": location or ""}
    return payload


async def update_graph_event(
    db: AsyncSession,
    connection: M365Connection,
    graph_event_id: str,
    payload: dict,
) -> Optional[str]:
    """Zmień wydarzenie w Outlooku właściciela połączenia (organizatora).

    Graph sam wysyła uczestnikom aktualizację. Zwraca nowy `changeKey`, żeby
    najbliższa synchronizacja nie nadpisała lokalnego wiersza tym samym stanem
    jeszcze raz. Błędy (`GraphRequestError`) lecą wyżej — wołający decyduje,
    czy to „nie jesteś organizatorem” (400/403), czy awaria.
    """
    async with GraphClient(connection, db) as gc:
        result = await gc.patch(f"/me/events/{graph_event_id}", json=payload)
    if isinstance(result, dict):
        return result.get("changeKey")
    return None


# ── Cancel ──────────────────────────────────────────────────────────────────

CancelOutcome = Literal["cancelled", "deleted", "gone"]
_CANCEL_COMMENT = "Spotkanie zostało odwołane."


async def cancel_graph_event(
    db: AsyncSession,
    connection: M365Connection,
    graph_event_id: str,
    *,
    comment: str = _CANCEL_COMMENT,
) -> CancelOutcome:
    """Odwołaj wydarzenie w Outlooku właściciela połączenia.

    - `cancel` (tylko organizator) wysyła uczestnikom odwołanie → `cancelled`;
    - 400/403 z `cancel` znaczy zwykle „nie jesteś organizatorem" (albo wpis
      bez uczestników) — wtedy `DELETE` zdejmuje wpis z kalendarza twórcy
      → `deleted`;
    - 404 na którymkolwiek kroku: w Outlooku już go nie ma → `gone`.

    Pozostałe błędy (5xx, 429 po ponowieniach, sieć) lecą wyżej — wołający
    NIE zmienia wtedy niczego lokalnie.
    """
    url = f"/me/events/{graph_event_id}"
    async with GraphClient(connection, db) as gc:
        try:
            await gc.post(f"{url}/cancel", json={"comment": comment}, expect_json=False)
            return "cancelled"
        except GraphRequestError as exc:
            if exc.status == 404:
                return "gone"
            if exc.status not in (400, 403):
                raise
        try:
            await gc.delete(url)
        except GraphRequestError as exc:
            if exc.status == 404:
                return "gone"
            raise
        return "deleted"


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
    # getSchedule tylko czyta — powtórka po utracie odpowiedzi jest bezpieczna.
    response = await gc.post(
        "/me/calendar/getSchedule", json=payload, retry_unsafe=True
    )
    return parse_free_busy_response(
        response, window_start=start_utc, interval_minutes=interval_minutes
    )
