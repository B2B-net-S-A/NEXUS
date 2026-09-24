"""Pobieranie transkryptów prepów z Teams (0369).

Kolejka = ``prep_meetings`` z ``next_fetch_at <= teraz`` i stanem ``waiting``
(także ``error``/``forbidden`` do ponowienia). Dla każdego prepu:

1. odśwież termin z Outlooka organizatora (przełożony albo odwołany w
   Outlooku prep nie może czekać na transkrypt w złym oknie),
2. znajdź spotkanie Teams i jego transkrypty,
3. brak transkryptu → ponowienie z rosnącym odstępem, a po
   ``TEAMS_PREP_FETCH_GIVE_UP_HOURS`` od końca → ``missing`` (prep bez nagrania),
4. jest → ``prep_transcripts`` (VTT, tekst, mówcy, udział kandydata) i ocena
   (``prep_review``) z notatką.

403 = aplikacja nie ma dostępu do tego kalendarza/spotkania (polityka dostępu
nie obejmuje organizatora) → ``forbidden``, ponowienie co 6 h BEZ zużywania
prób i sygnał w ``checks.teams_prep``. Do logu trafia wyłącznie klasa błędu
albo kod HTTP — nigdy treść odpowiedzi ani transkryptu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.candidate import Candidate
from app.models.prep_meeting import PrepMeeting, PrepTranscript
from app.models.user import User
from app.services import teams_vtt
from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

BATCH = 20
# Odstępy ponowień po kolejnych pustych odpowiedziach (minuty).
_BACKOFF_MINUTES = (10, 20, 40, 60, 120, 240, 480, 720)
_FORBIDDEN_RETRY = timedelta(hours=6)
_RETRY_STATES = ("waiting", "error", "forbidden")
# Na tyle wiersz jest „zajęty” przez bieg; nieudany bieg wraca po tym czasie.
_LEASE = timedelta(minutes=15)


def backoff(attempt: int) -> timedelta:
    idx = min(max(attempt, 1), len(_BACKOFF_MINUTES)) - 1
    return timedelta(minutes=_BACKOFF_MINUTES[idx])


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@dataclass
class RunStats:
    checked: int = 0
    fetched: int = 0
    missing: int = 0
    waiting: int = 0
    forbidden: int = 0
    errors: int = 0
    cancelled: int = 0
    fetched_ids: list[int] = field(default_factory=list)


async def _staff_for(
    db: AsyncSession, prep: PrepMeeting, event: CalendarEvent
) -> list[tuple[Optional[int], str]]:
    emails = {
        (a.get("address") or "").strip().lower()
        for a in (event.attendees or [])
        if isinstance(a, dict)
    }
    emails.add((prep.organizer_upn or "").strip().lower())
    emails.discard("")
    ids = {prep.organizer_user_id, prep.scheduled_by_user_id} - {None}
    rows = await db.execute(
        select(User.id, User.name).where(
            (func.lower(User.email).in_(emails)) | (User.id.in_(ids))
        )
    )
    return [(uid, name) for uid, name in rows.all() if name]


async def _refresh_event(prep: PrepMeeting, event: CalendarEvent) -> Optional[str]:
    """Termin z Outlooka organizatora. ``"cancelled"`` gdy odwołany/usunięty."""
    try:
        data = await teams_prep_graph.get_event(prep.organizer_upn, event.external_id)
    except GraphRequestError as exc:
        if exc.status == 404:
            return "cancelled"
        raise
    if data is None:
        return None
    if data.get("isCancelled"):
        return "cancelled"
    start, end = data.get("start"), data.get("end")
    if start and end:
        event.start_time = start
        event.end_time = end
    if data.get("join_url") and not event.online_meeting_url:
        # Graph oddał spotkanie bez linku przy tworzeniu — dociągamy go teraz,
        # inaczej prep kończyłby jako „bez nagrania”.
        event.online_meeting_url = data["join_url"]
    return None


def parse_contents(contents: list[str]) -> tuple[list[teams_vtt.Cue], int]:
    """Wypowiedzi ze wszystkich plików transkryptu i łączny czas rozmowy.

    Każdy plik (ponowne uruchomienie transkrypcji) liczy czas od zera, więc
    czas trwania to SUMA rozpiętości plików, nie rozpiętość całości.
    """
    cues: list[teams_vtt.Cue] = []
    duration = 0.0
    for raw in contents:
        part = teams_vtt.parse_vtt(raw)
        if part:
            duration += max(c.end for c in part) - min(c.start for c in part)
        cues.extend(part)
    return cues, max(0, round(duration))


async def _store(
    db: AsyncSession,
    prep: PrepMeeting,
    event: CalendarEvent,
    refs,
    contents: list[str],
    cues: list[teams_vtt.Cue],
    duration: int,
) -> None:
    candidate = await db.get(Candidate, prep.candidate_id)
    cand_name = (
        " ".join(p for p in (candidate.name, candidate.lastname) if p)
        if candidate
        else None
    )
    summary = teams_vtt.classify_speakers(
        cues, staff=await _staff_for(db, prep, event), candidate_name=cand_name
    )
    row = PrepTranscript(
        prep_meeting_id=prep.id,
        candidate_id=prep.candidate_id,
        job_id=prep.job_id,
        graph_transcript_ids=[r.id for r in refs],
        vtt="\n\n".join(contents),
        plain_text=teams_vtt.render_plain_text(cues),
        speakers=summary.speakers,
        candidate_seconds=summary.candidate_seconds,
        staff_seconds=summary.staff_seconds,
        unknown_seconds=summary.unknown_seconds,
        talk_share=Decimal(str(summary.talk_share))
        if summary.talk_share is not None
        else None,
        duration_seconds=duration,
    )
    db.add(row)


async def process_prep(
    db: AsyncSession, prep: PrepMeeting, now: datetime, stats: RunStats
) -> None:
    """Jeden prep. Zmienia stan wiersza; commit robi wołający."""
    event = await db.get(CalendarEvent, prep.calendar_event_id)
    if event is None or event.status == EventStatus.cancelled:
        prep.transcript_status = "cancelled"
        stats.cancelled += 1
        return
    stats.checked += 1
    try:
        if await _refresh_event(prep, event) == "cancelled":
            event.status = EventStatus.cancelled
            prep.transcript_status = "cancelled"
            stats.cancelled += 1
            return
        end = _aware(event.end_time) or _aware(event.start_time) or now
        ready_at = end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)
        if ready_at > now:
            prep.transcript_status = "waiting"
            prep.next_fetch_at = ready_at
            stats.waiting += 1
            return
        if not prep.organizer_aad_id:
            prep.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                prep.organizer_upn
            )
        if (
            prep.organizer_aad_id
            and not prep.online_meeting_id
            and event.online_meeting_url
        ):
            prep.online_meeting_id = await teams_prep_graph.find_online_meeting(
                prep.organizer_aad_id, event.online_meeting_url
            )
        refs = []
        if prep.organizer_aad_id and prep.online_meeting_id:
            refs = await teams_prep_graph.list_transcripts(
                prep.organizer_aad_id, prep.online_meeting_id
            )
        if not refs:
            prep.fetch_attempts += 1
            give_up = end + timedelta(hours=settings.TEAMS_PREP_FETCH_GIVE_UP_HOURS)
            if now >= give_up:
                prep.transcript_status = "missing"
                prep.next_fetch_at = None
                stats.missing += 1
            else:
                prep.transcript_status = "waiting"
                prep.next_fetch_at = now + backoff(prep.fetch_attempts)
                stats.waiting += 1
            return
        contents = [
            await teams_prep_graph.transcript_vtt(
                prep.organizer_aad_id, prep.online_meeting_id, r.id
            )
            for r in refs
        ]
        cues, duration = parse_contents(contents)
        if not cues:
            # Pusty albo nieczytelny transkrypt to brak danych, nie słaby prep:
            # bez oceny, bez wywołania modelu, bez dzwonka „Prep słaby”.
            prep.transcript_status = "missing"
            prep.next_fetch_at = None
            prep.last_error = "empty_transcript"
            stats.missing += 1
            return
        await _store(db, prep, event, refs, contents, cues, duration)
        prep.transcript_status = "fetched"
        prep.next_fetch_at = None
        prep.last_error = None
        stats.fetched += 1
        stats.fetched_ids.append(prep.id)
    except GraphRequestError as exc:
        if exc.status == 403:
            prep.transcript_status = "forbidden"
            prep.next_fetch_at = now + _FORBIDDEN_RETRY
            stats.forbidden += 1
        else:
            prep.transcript_status = "error"
            prep.fetch_attempts += 1
            prep.next_fetch_at = now + backoff(prep.fetch_attempts)
            stats.errors += 1
        prep.last_error = f"http_{exc.status}"
        logger.warning("teams prep %s: Graph %s", prep.id, exc.status)
    except Exception as exc:  # noqa: BLE001 — token, sieć, parser
        prep.transcript_status = "error"
        prep.fetch_attempts += 1
        prep.next_fetch_at = now + backoff(prep.fetch_attempts)
        prep.last_error = type(exc).__name__[:120]
        stats.errors += 1
        logger.warning("teams prep %s: fetch failed (%s)", prep.id, type(exc).__name__)


async def run_once(db: AsyncSession, now: Optional[datetime] = None) -> RunStats:
    """Jeden bieg kolejki, potem oceny pobranych prepów (każda we własnym commicie)."""
    from app.services import prep_review

    now = now or datetime.now(timezone.utc)
    stats = RunStats()
    # Dzierżawa zamiast blokady na czas wywołań Grapha: wiersze dostają
    # `next_fetch_at` za LEASE (drugi proces ich nie weźmie), commit zwalnia
    # blokady, a każdy prep ma własną krótką transakcję — odwołanie albo
    # przełożenie prepu w kalendarzu nie czeka na Microsoft.
    due = (
        select(PrepMeeting.id)
        .where(
            PrepMeeting.transcript_status.in_(_RETRY_STATES),
            PrepMeeting.next_fetch_at.isnot(None),
            PrepMeeting.next_fetch_at <= now,
        )
        .order_by(PrepMeeting.next_fetch_at.asc())
        .limit(BATCH)
        .with_for_update(skip_locked=True)
    )
    ids = list(
        (
            await db.execute(
                update(PrepMeeting)
                .where(PrepMeeting.id.in_(due.scalar_subquery()))
                .values(next_fetch_at=now + _LEASE)
                .returning(PrepMeeting.id)
                .execution_options(synchronize_session=False)
            )
        ).scalars()
    )
    await db.commit()
    for prep_id in ids:
        try:
            prep = await db.get(PrepMeeting, prep_id, populate_existing=True)
            if prep is None:
                continue
            await process_prep(db, prep, now, stats)
            await db.commit()
        except Exception:  # noqa: BLE001 — jeden prep nie zatrzymuje kolejki
            logger.exception("teams prep %s: batch step failed", prep_id)
            await db.rollback()
            stats.errors += 1
    for prep_id in stats.fetched_ids:
        try:
            await prep_review.review_prep(db, prep_id)
        except Exception:  # noqa: BLE001 — ocena nie może zatrzymać kolejki
            logger.exception("teams prep %s: review failed", prep_id)
            await db.rollback()
    return stats


def health_verdict(
    *, enabled: bool, configured: bool, forbidden_recent: int, errors_recent: int
) -> str:
    """Sonda ``checks.teams_prep`` — informacyjna, nie wpływa na 503."""
    if not enabled:
        return "unconfigured"
    if not configured:
        return "misconfigured"
    if forbidden_recent or errors_recent:
        return "degraded"
    return "healthy"


async def health_status(db: AsyncSession) -> str:
    from app.services.m365.teams_prep_auth import credentials_configured

    enabled = bool(
        settings.TEAMS_PREP_APP_ONLY_ENABLED or settings.TEAMS_PREP_TRANSCRIPTS_ENABLED
    )
    if not enabled:
        return "unconfigured"
    since = datetime.now(timezone.utc) - timedelta(hours=48)
    rows = (
        await db.execute(
            select(PrepMeeting.transcript_status, func.count())
            .where(
                PrepMeeting.updated_at >= since,
                PrepMeeting.transcript_status.in_(("forbidden", "error")),
            )
            .group_by(PrepMeeting.transcript_status)
        )
    ).all()
    counts = dict(rows)
    return health_verdict(
        enabled=True,
        configured=credentials_configured(),
        forbidden_recent=int(counts.get("forbidden", 0)),
        errors_recent=int(counts.get("error", 0)),
    )
