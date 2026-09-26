"""Schedule candidate follow-ups in Teams and collect their transcripts."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.services.calendar_privacy import PRIVATE_EVENT_TITLE
from app.models.candidate import Candidate
from app.models.followup_meeting import FollowupMeeting
from app.models.user import User
from app.services import prep_meetings, teams_vtt
from app.services.m365 import teams_prep_graph
from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
from app.services.m365.calendar import (
    M365_SOURCE,
    _build_event_payload,
    event_transaction_id,
)
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

NOTICE = (
    "Spotkanie odbywa się w Microsoft Teams. Będzie automatycznie nagrywane i "
    "transkrybowane na potrzeby obsługi Twojej rekrutacji przez B2B.NET S.A. "
    "Transkrypt jest przechowywany w NEXUS i dostępny wewnętrznie zespołowi rekrutacji. "
    "Jeśli nie chcesz nagrania, zgłoś to prowadzącemu przed rozpoczęciem rozmowy."
)


async def followup_for_event(
    db: AsyncSession, event_id: int
) -> Optional[FollowupMeeting]:
    return await db.scalar(
        select(FollowupMeeting).where(FollowupMeeting.calendar_event_id == event_id)
    )


async def app_only_meeting_for_event(db: AsyncSession, event_id: int):
    """Prep albo follow-up założony przez aplikację „NEXUS Teams Prep”.

    Oba żyją w kalendarzu organizatora, który zwykle nie ma połączonego konta
    M365 — edycja i odwołanie idą tą samą aplikacją (``teams_prep_graph``).
    Do rundy 6 audytu kalendarz znał tylko prep: zmiana terminu follow-upu
    kończyła się 409, a „Odwołaj” odwoływało go wyłącznie w NEXUSIE, choć
    kandydat miał zaproszenie z Teams.
    """
    prep = await prep_meetings.prep_for_event(db, event_id)
    if prep is not None:
        return prep
    return await followup_for_event(db, event_id)


async def create_followup_meeting(
    db: AsyncSession,
    *,
    candidate: Candidate,
    organizer: User,
    start: datetime,
    end: datetime,
    client_request_id: str,
) -> FollowupMeeting:
    if not prep_meetings.app_only_ready():
        raise HTTPException(
            status_code=503, detail="Integracja Teams nie jest skonfigurowana."
        )
    if not organizer.email or not candidate.email:
        raise HTTPException(
            status_code=422, detail="Prowadzący i kandydat muszą mieć adresy e-mail."
        )
    existing = await db.scalar(
        select(FollowupMeeting).where(
            FollowupMeeting.client_request_id == client_request_id
        )
    )
    if existing:
        if (
            existing.candidate_id != candidate.id
            or existing.organizer_user_id != organizer.id
        ):
            raise HTTPException(
                status_code=409, detail="Identyfikator żądania został już użyty."
            )
        return existing

    title = f"Follow-up: {candidate.name or ''} {candidate.lastname or ''}".strip()[
        :255
    ]
    payload = _build_event_payload(
        title=title,
        description=NOTICE,
        start=start,
        end=end,
        attendee_emails=[candidate.email],
        want_teams=True,
        transaction_id=event_transaction_id(
            owner_user_id=organizer.id,
            title=title,
            start=start,
            end=end,
            attendee_emails=[candidate.email],
            # Odcisk terminu w intencji — lustro prepu (runda 6 audytu).
            intent_id=(
                f"followup|{candidate.id}|{client_request_id}"
                f"|{organizer.id}|{start.isoformat()}|{end.isoformat()}"
            ),
        ),
    )
    try:
        created = await teams_prep_graph.create_event(organizer.email, payload)
    except AppOnlyTokenUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Integracja Teams nie jest skonfigurowana."
        ) from exc
    except GraphRequestError as exc:
        logger.warning("teams followup create: Graph %s", exc.status)
        raise HTTPException(
            status_code=409 if exc.status in (403, 404) else 502,
            detail="Outlook nie utworzył spotkania. Sprawdź dostęp prowadzącego do NEXUS-Meetings.",
        ) from exc

    start = created.start or start
    end = created.end or end
    event = CalendarEvent(
        title=title,
        description=NOTICE,
        event_type=EventType.meeting,
        start_time=start,
        end_time=end,
        all_day=False,
        attendees=[{"address": candidate.email}],
        candidate_id=candidate.id,
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
    meeting = FollowupMeeting(
        candidate_id=candidate.id,
        calendar_event_id=event.id,
        organizer_user_id=organizer.id,
        organizer_upn=organizer.email,
        client_request_id=client_request_id,
        transcription_setup="pending",
        transcript_status="waiting",
        next_fetch_at=end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES),
    )
    db.add(meeting)
    await db.flush()
    try:
        meeting.organizer_aad_id = await teams_prep_graph.resolve_user_id(
            organizer.email
        )
        if meeting.organizer_aad_id and created.join_url:
            meeting.online_meeting_id = await teams_prep_graph.find_online_meeting(
                meeting.organizer_aad_id, created.join_url
            )
        if not settings.TEAMS_PREP_AUTO_TRANSCRIBE:
            meeting.transcription_setup = "disabled"
        elif meeting.organizer_aad_id and meeting.online_meeting_id:
            await teams_prep_graph.enable_auto_transcription(
                meeting.organizer_aad_id, meeting.online_meeting_id
            )
            meeting.transcription_setup = "enabled"
        else:
            meeting.transcription_setup = "failed"
            meeting.last_error = "meeting_not_found"
    except GraphRequestError as exc:
        meeting.transcription_setup = "failed"
        meeting.last_error = f"setup_http_{exc.status}"
    except Exception as exc:  # noqa: BLE001 - invitation already exists
        meeting.transcription_setup = "failed"
        meeting.last_error = f"setup_{type(exc).__name__}"[:120]
    return meeting


async def fetch_due(db: AsyncSession, now: Optional[datetime] = None) -> int:
    """Fetch due transcripts with a row lease; failures remain retryable."""
    from app.services.prep_transcripts import backoff, parse_contents

    now = now or datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(FollowupMeeting)
            .where(
                FollowupMeeting.transcript_status.in_(
                    ("waiting", "error", "forbidden")
                ),
                FollowupMeeting.next_fetch_at <= now,
            )
            .order_by(FollowupMeeting.next_fetch_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for meeting in rows:
        meeting.next_fetch_at = now + timedelta(minutes=15)
    ids = [meeting.id for meeting in rows]
    await db.commit()
    fetched = 0
    for meeting_id in ids:
        try:
            meeting = await db.get(FollowupMeeting, meeting_id, populate_existing=True)
            if meeting is None:
                continue
            event = await db.get(CalendarEvent, meeting.calendar_event_id)
            if event is None or event.status == EventStatus.cancelled:
                meeting.transcript_status = "cancelled"
                meeting.next_fetch_at = None
                await db.commit()
                continue
            current = await teams_prep_graph.get_event(
                meeting.organizer_upn, event.external_id
            )
            if current and current.get("isCancelled"):
                meeting.transcript_status = "cancelled"
                meeting.next_fetch_at = None
                event.status = EventStatus.cancelled
                await db.commit()
                continue
            if current:
                event.start_time = current.get("start") or event.start_time
                event.end_time = current.get("end") or event.end_time
                event.online_meeting_url = (
                    current.get("join_url") or event.online_meeting_url
                )
            end = event.end_time or event.start_time
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            ready = end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)
            if ready > now:
                meeting.next_fetch_at = ready
                meeting.transcript_status = "waiting"
                await db.commit()
                continue
            if not meeting.organizer_aad_id:
                meeting.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                    meeting.organizer_upn
                )
            if (
                meeting.organizer_aad_id
                and not meeting.online_meeting_id
                and event.online_meeting_url
            ):
                meeting.online_meeting_id = await teams_prep_graph.find_online_meeting(
                    meeting.organizer_aad_id, event.online_meeting_url
                )
            refs = []
            if meeting.organizer_aad_id and meeting.online_meeting_id:
                refs = await teams_prep_graph.list_transcripts(
                    meeting.organizer_aad_id, meeting.online_meeting_id
                )
            if not refs:
                meeting.fetch_attempts += 1
                if now >= end + timedelta(
                    hours=settings.TEAMS_PREP_FETCH_GIVE_UP_HOURS
                ):
                    meeting.transcript_status = "missing"
                    meeting.next_fetch_at = None
                else:
                    meeting.transcript_status = "waiting"
                    meeting.next_fetch_at = now + backoff(meeting.fetch_attempts)
            else:
                contents = [
                    await teams_prep_graph.transcript_vtt(
                        meeting.organizer_aad_id, meeting.online_meeting_id, ref.id
                    )
                    for ref in refs
                ]
                cues, _ = parse_contents(contents)
                if cues:
                    meeting.transcript_vtt = "\n\n".join(contents)
                    meeting.transcript_text = teams_vtt.render_plain_text(cues)
                    meeting.transcript_fetched_at = now
                    meeting.transcript_status = "fetched"
                    meeting.next_fetch_at = None
                    meeting.last_error = None
                    fetched += 1
                else:
                    meeting.transcript_status = "missing"
                    meeting.next_fetch_at = None
                    meeting.last_error = "empty_transcript"
            await db.commit()
        except GraphRequestError as exc:
            if exc.status == 404:
                meeting.transcript_status = "cancelled"
                meeting.next_fetch_at = None
                await db.commit()
                continue
            meeting.transcript_status = "forbidden" if exc.status == 403 else "error"
            meeting.last_error = f"http_{exc.status}"
            meeting.fetch_attempts += 1
            meeting.next_fetch_at = now + (
                timedelta(hours=6)
                if exc.status == 403
                else backoff(meeting.fetch_attempts)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - retry one meeting without stopping others
            await db.rollback()
            logger.warning(
                "teams followup %s: fetch failed (%s)", meeting_id, type(exc).__name__
            )
            retry = await db.get(FollowupMeeting, meeting_id)
            if retry is not None:
                retry.transcript_status = "error"
                retry.fetch_attempts += 1
                retry.next_fetch_at = now + backoff(retry.fetch_attempts)
                retry.last_error = type(exc).__name__[:120]
                await db.commit()
    return fetched


# ── Usunięcie kandydata (art. 17 RODO, runda 6 audytu) ──────────────────────

ERASED_EVENT_TITLE = "Spotkanie z kandydatem (dane usunięte)"


def _without_address(attendees, email: Optional[str]):
    """Uczestnicy bez adresu usuwanej osoby (oba kształty: tekst i obiekt)."""
    if not isinstance(attendees, list):
        return []
    wanted = (email or "").strip().lower()
    kept = []
    for item in attendees:
        address = item.get("address") if isinstance(item, dict) else item
        if wanted and str(address or "").strip().lower() == wanted:
            continue
        kept.append(item)
    return kept


async def erase_candidate_meetings(
    db: AsyncSession, candidate: Candidate
) -> tuple[list[tuple[str, str]], dict]:
    """Przed usunięciem kandydata: odwołanie jego przyszłych spotkań w Teams
    i anonimizacja wydarzeń kalendarza. Bez commitu.

    ``calendar_events.candidate_id`` to ``SET NULL`` — wydarzenie przeżywa
    usunięcie osoby, a z nim tytuł „Prep 1: Imię Nazwisko…”, adres e-mail
    w uczestnikach i opis. Prep i follow-up w Teams zostawały też
    w kalendarzu organizatora z zaproszeniem kandydata. Zwraca listę
    ``(upn organizatora, id wydarzenia w Graphie)`` do odwołania PO commicie
    (``cancel_erased_meetings``) i liczniki do dowodu wykonania żądania.
    """
    from app.models.prep_meeting import PrepMeeting

    now = datetime.now(timezone.utc)
    pending: list[tuple[str, str, int]] = []
    for model in (PrepMeeting, FollowupMeeting):
        rows = (
            await db.execute(
                select(model.organizer_upn, CalendarEvent)
                .join(CalendarEvent, CalendarEvent.id == model.calendar_event_id)
                .where(
                    model.candidate_id == candidate.id,
                    CalendarEvent.status == EventStatus.scheduled,
                    CalendarEvent.start_time > now,
                    CalendarEvent.external_id.isnot(None),
                )
            )
        ).all()
        for upn, event in rows:
            # Runda 8 (R8-V3-9): status „odwołane” zapisuje dopiero udane
            # odwołanie w Teams (``_mark_cancelled`` po commicie). Do rundy 7
            # szedł tu przed Graphem, a żądanie przerwane w trakcie ponowień
            # (deploy, crash) zostawiało „odwołane” w NEXUSIE przy ważnym
            # zaproszeniu w Teams.
            pending.append((upn, event.external_id, event.id))
    events = (
        await db.scalars(
            select(CalendarEvent).where(CalendarEvent.candidate_id == candidate.id)
        )
    ).all()
    for event in events:
        # Runda 7 (R7-V1-7): prywatne spotkanie z Outlooka zostaje „Spotkaniem
        # prywatnym” — tytuł „Spotkanie z kandydatem (dane usunięte)” zdradzał
        # adminowi, HoR i Finansom, z kim było prywatne spotkanie.
        if event.title != PRIVATE_EVENT_TITLE:
            event.title = ERASED_EVENT_TITLE
        event.description = None
        event.attendees = _without_address(event.attendees, candidate.email)
    pending_ids = {event_id for _upn, _graph_id, event_id in pending}
    for event in events:
        if pending_ids and event.id in pending_ids:
            event.description = CANCEL_PENDING_NOTE
    await db.flush()
    return pending, {
        "teams_meetings_cancelled": len(pending),
        "calendar_events_anonymised": len(events),
    }


# Ponowienia odwołania w Teams po usunięciu kandydata (runda 7, R7-V1-6).
_CANCEL_RETRY_DELAYS: tuple[float, ...] = (1.0, 3.0)
# Opis na czas odwoływania — zostaje, jeśli żądanie przerwano przed Graphem.
CANCEL_PENDING_NOTE = (
    "Dane kandydata usunięte — spotkanie w Teams jest odwoływane. Jeśli ten "
    "opis nie zniknie, odwołaj je ręcznie w kalendarzu organizatora."
)
CANCEL_FAILED_NOTE = (
    "Nie udało się odwołać tego spotkania w Teams po usunięciu danych "
    "kandydata — odwołaj je ręcznie w kalendarzu organizatora."
)


async def _cancel_with_retry(upn: str, graph_event_id: str) -> bool:
    for attempt in range(len(_CANCEL_RETRY_DELAYS) + 1):
        try:
            await teams_prep_graph.cancel_event(
                upn, graph_event_id, "Spotkanie zostało odwołane."
            )
            return True
        except Exception as exc:  # noqa: BLE001 — Graph, token, sieć
            logger.warning(
                "candidate erasure: Teams meeting not cancelled (%s, attempt %s)",
                type(exc).__name__,
                attempt + 1,
            )
            if attempt < len(_CANCEL_RETRY_DELAYS):
                await asyncio.sleep(_CANCEL_RETRY_DELAYS[attempt])
    return False


async def _mark_cancelled(event_ids: list[int]) -> None:
    """Odwołane w Teams → „odwołane” w NEXUSIE (runda 8, R8-V3-9)."""
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            events = (
                await db.scalars(
                    select(CalendarEvent).where(CalendarEvent.id.in_(event_ids))
                )
            ).all()
            for event in events:
                event.status = EventStatus.cancelled
                event.description = None
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — usunięcie już się stało
        logger.error(
            "candidate erasure: cancelled state not saved (%s)", type(exc).__name__
        )


async def _restore_uncancelled(event_ids: list[int]) -> None:
    """Spotkanie, którego Teams nie odwołał, nie może udawać odwołanego.

    Wydarzenie zostaje „zaplanowane” (``erase_candidate_meetings`` nie zmienia
    już statusu przed Graphem); zaproszenie kandydata dalej wisi w kalendarzu
    organizatora, więc opis prosi o ręczne odwołanie.
    """
    from app.core.database import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            events = (
                await db.scalars(
                    select(CalendarEvent).where(CalendarEvent.id.in_(event_ids))
                )
            ).all()
            for event in events:
                event.status = EventStatus.scheduled
                event.description = CANCEL_FAILED_NOTE
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — usunięcie już się stało
        logger.error(
            "candidate erasure: event state not restored (%s)", type(exc).__name__
        )
        return
    logger.error(
        "candidate erasure: %s Teams meeting(s) left uncancelled — cancel manually",
        len(event_ids),
    )


async def cancel_erased_meetings(pending: list[tuple[str, str, int]]) -> int:
    """Odwołanie w Teams po commicie usunięcia. Nigdy nie rzuca; log bez danych.

    Runda 7 (R7-V1-6): każde odwołanie ma ponowienia, a to, którego Teams nie
    przyjął, wraca w NEXUSIE na „zaplanowane” z prośbą o ręczne odwołanie —
    dotąd NEXUS pokazywał „odwołane”, a kandydat miał ważne zaproszenie.
    """
    cancelled_ids: list[int] = []
    failed: list[int] = []
    for upn, graph_event_id, event_id in pending:
        if await _cancel_with_retry(upn, graph_event_id):
            cancelled_ids.append(event_id)
        else:
            failed.append(event_id)
    if cancelled_ids:
        await _mark_cancelled(cancelled_ids)
    if failed:
        await _restore_uncancelled(failed)
    return len(cancelled_ids)
