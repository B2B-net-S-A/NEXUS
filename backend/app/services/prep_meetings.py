"""Prep 1 / Prep 2 z kandydatem przez Teams — zakładanie z NEXUSA (0370).

Przed każdą rozmową u klienta są dwa prepy (decyzja Artura 23.09.2026):
Prep 1 prowadzi Delivery Lead rekrutacji, Prep 2 — rekruter kandydata.
NEXUS podpowiada organizatora; spotkanie powstaje w JEGO kalendarzu przez
aplikację (``teams_prep_graph``), z linkiem Teams, zaproszeniem kandydata,
akapitem o nagrywaniu i — gdy się da — automatyczną transkrypcją.

Porażka kroków PO utworzeniu spotkania (identyfikator spotkania Teams,
włączenie transkrypcji) nie cofa prepu: spotkanie już istnieje w Outlooku
i kandydat dostał zaproszenie. Zostaje ślad ``transcription_setup=failed``
i ostrzeżenie „włącz transkrypcję ręcznie”.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.prep_meeting import PrepMeeting
from app.models.user import User
from app.services import interview_slots
from app.services.m365 import teams_prep_auth, teams_prep_graph
from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
from app.services.m365.calendar import (
    M365_SOURCE,
    _build_event_payload,
    event_transaction_id,
)
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

# Treść informacji o nagrywaniu w zaproszeniu. Wersja robocza do akceptacji
# prawnej — zmiana treści = nowa wersja (jak zgoda na stronie kariery).
PREP_NOTICE_VERSION = "2026-09-23"
PREP_NOTICE_TEXT = (
    "Ta rozmowa jest nagrywana i transkrybowana w Microsoft Teams wyłącznie "
    "po to, żeby dobrze przygotować Cię do rozmowy z klientem. Administratorem "
    "danych jest B2B.NET S.A. Transkrypt zostaje wewnątrz B2B.NET i nie trafia "
    "do klienta. Jeśli nie chcesz nagrania, powiedz o tym na początku rozmowy."
)


def prep_title(prep_no: int, candidate: Candidate, job: Job) -> str:
    """Tytuł widzi też kandydat — bez nazwy klienta."""
    who = " ".join(p for p in (candidate.name, candidate.lastname) if p) or "Kandydat"
    return f"Prep {prep_no}: {who} — {job.title or 'rekrutacja'}"[:255]


def prep_description(extra: Optional[str]) -> str:
    parts = [p for p in ((extra or "").strip(), PREP_NOTICE_TEXT) if p]
    return "\n\n".join(parts)


async def suggest_organizer_id(
    db: AsyncSession, *, job: Job, candidate_id: int, prep_no: int
) -> Optional[int]:
    """Prep 1 → Delivery Lead rekrutacji, Prep 2 → rekruter kandydata.

    Brak DL-a przy Prepie 1 → rekruter (ktoś musi go poprowadzić); rekruter
    kandydata liczy ``interview_slots.default_recruiter_id`` (ta sama reguła
    co przy terminach od klienta).
    """
    recruiter = await interview_slots.default_recruiter_id(
        db, candidate_id=candidate_id, job_id=job.id
    )
    if prep_no == 1:
        return job.delivery_lead_id or recruiter
    return recruiter or job.delivery_lead_id


def app_only_ready() -> bool:
    return bool(settings.TEAMS_PREP_APP_ONLY_ENABLED) and (
        teams_prep_auth.credentials_configured()
    )


async def active_prep(
    db: AsyncSession, *, candidate_id: int, job_id: int, prep_no: int
) -> Optional[PrepMeeting]:
    """Prep o tym numerze w BIEŻĄCEJ rundzie rozmów pary.

    Nie liczą się: odwołany, bez nagrania (trzeba go powtórzyć) i prep sprzed
    rozmowy u klienta, która już się odbyła (kolejna runda ma własne prepy).
    """
    round_start = await db.scalar(
        select(func.max(CalendarEvent.start_time)).where(
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job_id,
            CalendarEvent.event_type == EventType.client_interview,
            CalendarEvent.status != EventStatus.cancelled,
            CalendarEvent.start_time <= func.now(),
        )
    )
    q = (
        select(PrepMeeting)
        .join(CalendarEvent, CalendarEvent.id == PrepMeeting.calendar_event_id)
        .where(
            PrepMeeting.candidate_id == candidate_id,
            PrepMeeting.job_id == job_id,
            PrepMeeting.prep_no == prep_no,
            PrepMeeting.transcript_status != "missing",
            CalendarEvent.status != EventStatus.cancelled,
        )
    )
    if round_start is not None:
        q = q.where(CalendarEvent.start_time > round_start)
    return await db.scalar(q.order_by(PrepMeeting.id.desc()).limit(1))


async def prep_for_event(db: AsyncSession, event_id: int) -> Optional[PrepMeeting]:
    return await db.scalar(
        select(PrepMeeting).where(PrepMeeting.calendar_event_id == event_id)
    )


@dataclass(frozen=True)
class CreatedPrep:
    event: CalendarEvent
    prep: PrepMeeting


def _fetch_after(end: datetime) -> datetime:
    aware = end if end.tzinfo is not None else end.replace(tzinfo=timezone.utc)
    return aware + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)


async def create_prep(
    db: AsyncSession,
    *,
    actor: User,
    candidate: Candidate,
    job: Job,
    prep_no: int,
    organizer: User,
    start: datetime,
    end: datetime,
    extra_attendees: list[User],
    note: Optional[str],
    client_request_id: Optional[str],
) -> CreatedPrep:
    """Spotkanie w kalendarzu organizatora + wiersze NEXUSA. Flush, bez commitu."""
    if not organizer.email:
        raise HTTPException(
            status_code=422,
            detail="Organizator nie ma adresu e-mail w NEXUSIE — nie da się "
            "założyć spotkania w jego kalendarzu.",
        )
    if not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="Kandydat nie ma adresu e-mail — nie da się wysłać zaproszenia.",
        )

    title = prep_title(prep_no, candidate, job)
    description = prep_description(note)
    attendees = [candidate.email]
    for user in extra_attendees:
        if user.email and user.email.lower() not in {a.lower() for a in attendees}:
            if user.id != organizer.id:
                attendees.append(user.email)
    payload = _build_event_payload(
        title=title,
        description=description,
        start=start,
        end=end,
        attendee_emails=attendees,
        want_teams=True,
        transaction_id=event_transaction_id(
            owner_user_id=organizer.id,
            title=title,
            start=start,
            end=end,
            attendee_emails=attendees,
            intent_id=(
                f"prep|{candidate.id}|{job.id}|{prep_no}|{client_request_id}"
                if client_request_id
                else None
            ),
        ),
    )

    try:
        created = await teams_prep_graph.create_event(organizer.email, payload)
    except AppOnlyTokenUnavailable as exc:
        logger.warning("teams prep: no app-only token (%s)", type(exc).__name__)
        raise HTTPException(
            status_code=503,
            detail="Integracja z Teams nie jest skonfigurowana. W NEXUSIE nic "
            "nie zostało zapisane.",
        ) from exc
    except GraphRequestError as exc:
        logger.warning("teams prep: create event Graph %s", exc.status)
        if exc.status in (403, 404):
            raise HTTPException(
                status_code=409,
                detail="Microsoft 365 nie pozwolił założyć spotkania w kalendarzu "
                "organizatora — zwykle dlatego, że ta osoba nie jest w grupie "
                "NEXUS-Meetings. Poproś administratora o dopisanie.",
            ) from exc
        raise HTTPException(
            status_code=502,
            detail="Outlook nie przyjął spotkania — spróbuj ponownie za chwilę. "
            "W NEXUSIE nic nie zostało zapisane.",
        ) from exc

    event = CalendarEvent(
        title=title,
        description=description,
        event_type=EventType.prep_call,
        start_time=start,
        end_time=end,
        all_day=False,
        attendees=[{"address": a} for a in attendees],
        candidate_id=candidate.id,
        job_id=job.id,
        status=EventStatus.scheduled,
        external_source=M365_SOURCE,
        external_id=created.graph_event_id,
        created_by=organizer.id,
        operational_owner_id=organizer.id,
        m365_change_key=created.change_key,
        online_meeting_url=created.join_url,
        reminder_minutes=15,
    )
    db.add(event)
    await db.flush()

    prep = PrepMeeting(
        calendar_event_id=event.id,
        candidate_id=candidate.id,
        job_id=job.id,
        prep_no=prep_no,
        organizer_user_id=organizer.id,
        organizer_upn=organizer.email,
        scheduled_by_user_id=actor.id,
        transcription_setup="pending",
        transcript_status="waiting",
        next_fetch_at=_fetch_after(end),
    )
    db.add(prep)
    await db.flush()
    await setup_transcription(prep, join_url=created.join_url)
    await db.flush()
    return CreatedPrep(event=event, prep=prep)


async def setup_transcription(prep: PrepMeeting, *, join_url: Optional[str]) -> None:
    """Identyfikatory spotkania Teams i automatyczna transkrypcja. Nigdy nie rzuca."""
    try:
        if not prep.organizer_aad_id:
            prep.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                prep.organizer_upn
            )
        if prep.organizer_aad_id and join_url and not prep.online_meeting_id:
            prep.online_meeting_id = await teams_prep_graph.find_online_meeting(
                prep.organizer_aad_id, join_url
            )
        if not settings.TEAMS_PREP_AUTO_TRANSCRIBE:
            prep.transcription_setup = "disabled"
            return
        if not (prep.organizer_aad_id and prep.online_meeting_id):
            prep.transcription_setup = "failed"
            prep.last_error = "meeting_not_found"
            return
        await teams_prep_graph.enable_auto_transcription(
            prep.organizer_aad_id, prep.online_meeting_id
        )
        prep.transcription_setup = "enabled"
    except GraphRequestError as exc:
        prep.transcription_setup = "failed"
        prep.last_error = f"setup_http_{exc.status}"
        logger.warning(
            "teams prep %s: transcription setup Graph %s", prep.id, exc.status
        )
    except Exception as exc:  # noqa: BLE001 — sieć, token
        prep.transcription_setup = "failed"
        prep.last_error = f"setup_{type(exc).__name__}"[:120]
        logger.warning("teams prep %s: transcription setup failed", prep.id)


def reschedule_fetch(prep: PrepMeeting, end: datetime) -> None:
    """Nowy termin spotkania = nowy moment pytania o transkrypt.

    Prep „bez nagrania” (albo z błędem) przełożony na nowy termin znów czeka
    na transkrypt — spotkanie jeszcze się nie odbyło.
    """
    if prep.transcript_status in ("waiting", "missing", "error", "forbidden"):
        prep.transcript_status = "waiting"
        prep.fetch_attempts = 0
        prep.next_fetch_at = _fetch_after(end)


async def suggestion_summary(
    db: AsyncSession, *, job: Job, candidate_id: int
) -> dict[int, Optional[int]]:
    """Podpowiedzi organizatora dla obu prepów (okno „Zaplanuj prep”)."""
    return {
        n: await suggest_organizer_id(db, job=job, candidate_id=candidate_id, prep_no=n)
        for n in (1, 2)
    }
