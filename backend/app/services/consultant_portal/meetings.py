"""Rezerwacja rozmowy: konsultant wybiera osobę i termin, spotkanie zakłada wsparcie@.

Organizatorem jest ``CONSULTANT_PORTAL_MAILBOX`` przez rejestrację „NEXUS Teams Prep”
(``m365.teams_prep_graph``). Konto i polityka Teams nie są jeszcze skonfigurowane, więc
brak konfiguracji daje czytelną odmowę, a nie błąd.

* Termin rezerwuje wiersz ``pending`` z częściowym unikatem (osoba, początek), zatwierdzony
  PRZED wywołaniem Grapha: dwie osoby klikające ten sam termin nie założą dwóch spotkań.
* Kalendarz, którego nie da się przeczytać, nie daje terminów. Inaczej niż przy prepach,
  gdzie człowiek widzi ostrzeżenie: konsultant nie ma jak zauważyć kolizji.
* Transkrypcję uzbraja pętla (``transcripts.arm_pending``): Graph publikuje spotkanie
  z opóźnieniem, a konsultant nie może czekać na to w żądaniu.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional, Sequence
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.scheduling import DEFAULT_TZ, is_business_day
from app.models.admin_case import AdminCaseComment
from app.models.back_office import BoTeamMember
from app.models.consultant_portal import CpMeeting, CpRating
from app.models.user import User
from app.services import prep_availability, prep_meetings
from app.services.consultant_portal import content
from app.services.consultant_portal.auth import PortalContext, PortalError
from app.services.consultant_portal_schema import REASON_MAX, TOPICS
from app.services.m365 import teams_prep_graph
from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
from app.services.m365.calendar import _build_event_payload
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

MEETING_MINUTES = 20
STEP_MINUTES = 30
SEARCH_DAYS = 7
SLOTS_PER_HOST = 8
MIN_LEAD = timedelta(hours=2)
WORK_START = time(9, 0)
WORK_END = time(16, 0)
MAX_UPCOMING = 3
HOST_TEAMS: tuple[str, ...] = ("care", "finance", "contracts")
TEAM_LABELS: dict[str, str] = {
    "care": "Opieka",
    "finance": "Finanse",
    "contracts": "Umowy",
}

BOOKING_OFF = (
    "Rezerwacja rozmów jest chwilowo niedostępna. Załóż zgłoszenie, a oddzwonimy."
)
SLOT_TAKEN = "Ten termin właśnie się zajął. Wybierz inny."
SLOT_INVALID = "Tego terminu nie ma już na liście. Wybierz inny."
HOST_INVALID = "Tej osoby nie ma na liście. Wybierz inną."
TOO_MANY = (
    "Masz już kilka umówionych rozmów. Odwołaj jedną albo poczekaj, aż się odbędą."
)
NOT_FOUND = "Nie ma takiej rozmowy."
CANNOT_CANCEL = "Tej rozmowy nie można już odwołać."
CANCEL_FAILED = "Nie udało się odwołać rozmowy. Spróbuj ponownie za chwilę."

INVITE_NOTE = (
    "Rozmowa w Teams jest spisywana, żebyśmy nie gubili ustaleń. Nie zachowujemy wideo. "
    "Pełny zapis widzi prowadzący, kierownik i osoba prowadząca sprawę, "
    "a podsumowanie także zespół obsługi spraw."
)


def organizer_upn() -> Optional[str]:
    return (settings.CONSULTANT_PORTAL_MAILBOX or "").strip() or None


def booking_ready() -> bool:
    return organizer_upn() is not None and prep_meetings.app_only_ready()


def slots_for(
    *,
    now: datetime,
    busy: Optional[Sequence[prep_availability.Interval]],
    booked: Sequence[prep_availability.Interval] = (),
    tz: str = DEFAULT_TZ,
    limit: int = SLOTS_PER_HOST,
) -> list[datetime]:
    """Wolne początki rozmów (UTC). ``busy=None`` = kalendarz nieznany, więc pusto."""

    if busy is None:
        return []
    zone = ZoneInfo(tz)
    length = timedelta(minutes=MEETING_MINUTES)
    earliest = now + MIN_LEAD
    blocks = [*busy, *booked]
    out: list[datetime] = []
    day: date = now.astimezone(zone).date()
    for offset in range(SEARCH_DAYS * 2):
        current = day + timedelta(days=offset)
        noon = datetime.combine(current, time(12, 0), tzinfo=zone)
        if not is_business_day(noon):
            continue
        cursor = datetime.combine(current, WORK_START, tzinfo=zone)
        last = datetime.combine(current, WORK_END, tzinfo=zone) - length
        while cursor <= last:
            end = cursor + length
            if cursor >= earliest and not any(
                cursor < b_end and b_start < end for b_start, b_end in blocks
            ):
                out.append(cursor.astimezone(timezone.utc))
                if len(out) >= limit:
                    return out
            cursor += timedelta(minutes=STEP_MINUTES)
    return out


async def _host_rows(db: AsyncSession) -> list[tuple[User, str]]:
    rows = (
        await db.execute(
            select(User, BoTeamMember.team)
            .join(BoTeamMember, BoTeamMember.user_id == User.id)
            .where(BoTeamMember.team.in_(HOST_TEAMS), User.is_active.is_(True))
            .order_by(BoTeamMember.team, User.name)
        )
    ).all()
    seen: set[int] = set()
    out: list[tuple[User, str]] = []
    for user, team in rows:
        if user.id not in seen and user.email:
            seen.add(user.id)
            out.append((user, team))
    return out


async def _booked_blocks(
    db: AsyncSession, host_ids: Sequence[int], *, start: datetime
) -> dict[int, list[prep_availability.Interval]]:
    out: dict[int, list[prep_availability.Interval]] = {}
    if not host_ids:
        return out
    rows = (
        await db.execute(
            select(CpMeeting.host_user_id, CpMeeting.start_at, CpMeeting.end_at).where(
                CpMeeting.host_user_id.in_(host_ids),
                CpMeeting.status.in_(("pending", "booked")),
                CpMeeting.end_at > start,
            )
        )
    ).all()
    for host_id, begin, end in rows:
        out.setdefault(host_id, []).append((begin, end))
    return out


async def _busy_by_email(
    emails: Sequence[str], *, now: datetime
) -> dict[str, Optional[list[prep_availability.Interval]]]:
    """Organizator idzie pierwszy: jego skrzynka musi być w zakresie aplikacji."""

    anchor = organizer_upn()
    return await prep_availability.busy_blocks(
        [anchor, *emails] if anchor else list(emails),
        start=now,
        end=now + timedelta(days=SEARCH_DAYS * 2),
    )


async def hosts_with_slots(
    db: AsyncSession, *, topic: str, now: datetime
) -> dict[str, Any]:
    if not booking_ready():
        return {"available": False, "message": BOOKING_OFF, "hosts": []}
    rows = await _host_rows(db)
    busy = await _busy_by_email([user.email for user, _team in rows], now=now)
    booked = await _booked_blocks(db, [user.id for user, _team in rows], start=now)
    preferred = content.TOPIC_TEAMS[topic]
    hosts = [
        {
            "id": user.id,
            "name": user.name,
            "team": TEAM_LABELS.get(team, team),
            "matches_topic": team == preferred,
            "calendar_available": busy.get(user.email.lower()) is not None,
            "slots": [
                slot.isoformat()
                for slot in slots_for(
                    now=now,
                    busy=busy.get(user.email.lower()),
                    booked=booked.get(user.id, ()),
                )
            ],
        }
        for user, team in rows
    ]
    hosts.sort(key=lambda host: (not host["matches_topic"], host["name"] or ""))
    return {"available": True, "message": None, "hosts": hosts}


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def book(
    db: AsyncSession,
    context: PortalContext,
    *,
    host_user_id: int,
    start: datetime,
    topic: str,
    reason: str,
    now: datetime,
) -> CpMeeting:
    if topic not in TOPICS:
        raise PortalError("Wybierz temat rozmowy.")
    if not booking_ready():
        raise PortalError(BOOKING_OFF, status=503, code="booking_off")
    consultant = context.consultant
    start = _aware(start).astimezone(timezone.utc)
    upcoming = await db.scalar(
        select(func.count())
        .select_from(CpMeeting)
        .where(
            CpMeeting.contract_id.in_(consultant.contract_ids),
            CpMeeting.status.in_(("pending", "booked")),
            CpMeeting.end_at > now,
        )
    )
    if (upcoming or 0) >= MAX_UPCOMING:
        raise PortalError(TOO_MANY, status=409, code="too_many")
    host = next(
        (user for user, _team in await _host_rows(db) if user.id == host_user_id), None
    )
    if host is None:
        raise PortalError(HOST_INVALID, status=422, code="host_invalid")
    busy = await _busy_by_email([host.email], now=now)
    booked = await _booked_blocks(db, [host.id], start=now)
    free = slots_for(
        now=now,
        busy=busy.get(host.email.lower()),
        booked=booked.get(host.id, ()),
        limit=SEARCH_DAYS * 2 * 14,
    )
    if start not in free:
        raise PortalError(SLOT_INVALID, status=409, code="slot_invalid")
    upn = organizer_upn() or ""
    end = start + timedelta(minutes=MEETING_MINUTES)
    meeting = CpMeeting(
        contract_id=consultant.contract_id,
        host_user_id=host.id,
        topic=topic,
        reason=reason.replace("\x00", "").strip()[:REASON_MAX],
        start_at=start,
        end_at=end,
        status="pending",
        client_request_id=uuid4().hex,
        organizer_upn=upn,
        transcript_status="waiting",
        created_at=now,
        updated_at=now,
    )
    db.add(meeting)
    request_id = meeting.client_request_id
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise PortalError(SLOT_TAKEN, status=409, code="slot_taken") from exc
    meeting_id = meeting.id
    payload = _build_event_payload(
        title=f"Rozmowa z B2B.net: {content.TOPIC_LABELS[topic]}",
        description=f"<p>{INVITE_NOTE}</p>",
        start=start,
        end=end,
        attendee_emails=[host.email, consultant.email],
        want_teams=True,
        transaction_id=request_id,
    )
    try:
        created = await teams_prep_graph.create_event(upn, payload)
    except (GraphRequestError, AppOnlyTokenUnavailable, httpx.HTTPError) as exc:
        logger.warning(
            "consultant_portal_booking: create_event failed (%s)", type(exc).__name__
        )
        row = await db.get(CpMeeting, meeting_id)
        if row is not None:
            row.status = "failed"
            row.transcript_status = "cancelled"
            row.last_error = type(exc).__name__[:200]
            row.updated_at = now
            await db.commit()
        raise PortalError(BOOKING_OFF, status=503, code="booking_failed") from exc
    row = await db.get(CpMeeting, meeting_id)
    assert row is not None
    row.status = "booked"
    row.graph_event_id = created.graph_event_id
    row.join_url = created.join_url
    row.next_fetch_at = end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)
    row.updated_at = now
    case = await content.open_portal_case(
        db,
        contract_id=consultant.contract_id,
        title=f"Rozmowa: {content.TOPIC_LABELS[topic]}",
        description=row.reason or None,
        now=now,
    )
    row.case_id = case.id
    await db.flush()
    return row


async def cancel(
    db: AsyncSession, context: PortalContext, meeting_id: int, *, now: datetime
) -> CpMeeting:
    meeting = await db.get(CpMeeting, meeting_id)
    if meeting is None or meeting.contract_id not in context.consultant.contract_ids:
        raise PortalError(NOT_FOUND, status=404, code="not_found")
    if meeting.status != "booked" or _aware(meeting.start_at) <= now:
        raise PortalError(CANNOT_CANCEL, status=409, code="cannot_cancel")
    if meeting.graph_event_id and meeting.organizer_upn:
        try:
            await teams_prep_graph.cancel_event(
                meeting.organizer_upn,
                meeting.graph_event_id,
                "Konsultant odwołał rozmowę.",
            )
        except (GraphRequestError, AppOnlyTokenUnavailable, httpx.HTTPError) as exc:
            logger.warning(
                "consultant_portal_booking: cancel failed (%s)", type(exc).__name__
            )
            raise PortalError(CANCEL_FAILED, status=503, code="cancel_failed") from exc
    meeting.status = "cancelled"
    meeting.transcript_status = "cancelled"
    meeting.next_fetch_at = None
    meeting.updated_at = now
    if meeting.case_id:
        db.add(
            AdminCaseComment(
                case_id=meeting.case_id,
                author_user_id=None,
                body="Konsultant odwołał rozmowę w portalu.",
            )
        )
    return meeting


async def own_meetings(
    db: AsyncSession, context: PortalContext, *, now: datetime, limit: int = 30
) -> list[dict[str, Any]]:
    """Lista dla konsultanta: bez transkryptu, podsumowania i ocen innych."""

    rows = (
        await db.execute(
            select(CpMeeting, User.name, CpRating.id)
            .outerjoin(User, User.id == CpMeeting.host_user_id)
            .outerjoin(CpRating, CpRating.meeting_id == CpMeeting.id)
            .where(
                CpMeeting.contract_id.in_(context.consultant.contract_ids),
                CpMeeting.status.in_(("booked", "cancelled")),
            )
            .order_by(CpMeeting.start_at.desc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": meeting.id,
            "topic": meeting.topic,
            "topic_label": content.TOPIC_LABELS[meeting.topic],
            "host": host_name,
            "start_at": meeting.start_at.isoformat(),
            "end_at": meeting.end_at.isoformat(),
            "status": meeting.status,
            "join_url": meeting.join_url
            if meeting.status == "booked" and _aware(meeting.end_at) > now
            else None,
            "can_cancel": meeting.status == "booked" and _aware(meeting.start_at) > now,
            "can_rate": meeting.status == "booked"
            and _aware(meeting.end_at) <= now
            and rating_id is None,
        }
        for meeting, host_name, rating_id in rows
    ]
