"""Prepy w Teams (0370): planowanie Prep 1/2, transkrypt i ocena prepu.

* ``GET  /api/interview-cycle/preps/options`` — czy integracja działa,
  podpowiedzi organizatora dla obu prepów i zespół rekrutacji do wyboru.
* ``POST /api/interview-cycle/preps`` — zakłada prep w kalendarzu
  organizatora (Teams, zaproszenie kandydata, automatyczna transkrypcja).
* ``GET  /api/interview-cycle/preps/{event_id}`` — stan prepu, zaproszeni,
  ocena i ``can_edit``.
* ``PATCH /api/interview-cycle/preps/{event_id}`` — nowy termin, zaproszeni
  albo prowadzący (17.10.2026, decyzje D1–D4).
* ``POST /api/interview-cycle/preps/{event_id}/cancel`` — odwołanie.
* ``GET  /api/interview-cycle/preps/{event_id}/transcript`` — pełny transkrypt
  (zespół rekrutacji, jak każdy odczyt rekrutacji).
* ``GET  /api/interview-cycle/prep-quality`` — raport jakości prepów per
  organizator (admin i Head of Recruitment) i rozmowy bez Prepu 2 per osoba.
* ``POST /api/interview-cycle/prep2-skip`` — rozmowa bez Prepu 2: powód
  i telefon do kandydata przed rozmową (0482, wyjątek tuż przed rozmową).
* ``POST /api/interview-cycle/prep2-skip/{skip_id}/call-done`` — telefon
  przed rozmową odbyty.

Sekcja Pipeline + role zapisu kalendarza + członkostwo w rekrutacji — te same
bramki co pozostałe trasy „Rozmów u klienta”. Zmianę i odwołanie prepu
rozstrzyga ``prep_meetings.user_can_edit_prep`` (ludzie pary), nie
właściciel wydarzenia z ``calendar_access``.
"""

from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, EmailStr, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calendar_access import (
    CALENDAR_EVENT_CANCELLED,
    CALENDAR_EVENT_UPDATED,
    _attendee_emails,
    record_calendar_audit,
    user_is_override,
)
from app.api.candidate_access import user_has_candidate_read
from app.api.recruitment_access import (
    CalendarWriteAccess,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_job_read_access,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.prep_meeting import (
    Prep2Skip,
    PrepMeeting,
    PrepReview,
    PrepTranscript,
)
from app.models.user import User
from app.services import (
    interview_slots,
    prep2_skips,
    prep_availability,
    prep_invitation,
    prep_meetings,
    prep_notifications,
    prep_review,
    teams_vtt,
)
from app.services.job_membership import list_job_member_ids
from app.services.job_working_title import cv_role_title_for_job

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


def _aware(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class PersonOut(BaseModel):
    id: int
    name: str


class PersonOption(BaseModel):
    """Osoba do zaproszenia na prep — każdy aktywny w NEXUSIE (decyzja D1)."""

    id: int
    name: str
    role: Optional[str] = None
    in_team: bool = False


class AttendeeOut(BaseModel):
    """Zaproszony na prep (bez kandydata); ``user_id`` puste = spoza NEXUSA."""

    email: str
    user_id: Optional[int] = None
    name: Optional[str] = None


class InvitationPreviewOut(BaseModel):
    """Zaproszenie, które dostanie kandydat — podgląd w oknie „Zaplanuj prep”.

    ``body`` niesie pola ``{note}`` (wiadomość z formularza) i ``{organizer}``
    (podpis); podstawia je przeglądarka, a serwer przy zapisie składa treść
    tą samą funkcją (``prep_invitation.text``). ``interview_line`` to akapit
    o terminie rozmowy — serwer pomija go, gdy prep nie jest przed rozmową,
    więc podgląd też musi umieć go zdjąć.
    """

    title: str
    body: str
    interview_line: Optional[str] = None


class PrepFollowupOut(BaseModel):
    key: str
    label: str
    reason: Optional[str] = None
    note: Optional[str] = None


class PrepOptionsOut(BaseModel):
    enabled: bool
    auto_transcribe: bool
    suggested: dict[int, Optional[PersonOut]]
    team: list[PersonOut]
    people: list[PersonOption] = []
    notice: str
    invitation: dict[int, InvitationPreviewOut] = {}
    # Notatka na Prep 2 z oceny Prepu 1 pary (ocena v2, 22.10.2026) — okno
    # „Zaplanuj Prep 2” pokazuje ją prowadzącemu; pusta = brak oceny Prepu 1.
    prep1_followup: list[PrepFollowupOut] = []


async def _client_name(db: AsyncSession, job: Job) -> Optional[str]:
    if job.client_id is None:
        return None
    return await db.scalar(select(Client.name).where(Client.id == job.client_id))


class PrepCreate(BaseModel):
    candidate_id: int
    job_id: int
    prep_no: Literal[1, 2]
    organizer_user_id: int
    start: datetime
    end: datetime
    attendee_user_ids: list[int] = Field(default_factory=list, max_length=10)
    attendee_emails: list[EmailStr] = Field(default_factory=list, max_length=10)
    note: Optional[str] = Field(default=None, max_length=2000)
    client_request_id: Optional[str] = Field(default=None, max_length=80)
    # Planujący widział, że prowadzący ma wtedy zajęte, i zapisuje mimo to
    # (22.10.2026). Bez tego kolizja z kalendarza = 409 PREP_SLOT_BUSY.
    accept_busy: bool = False
    # Termin rozmowy wybrany w oknie „Umów rozmowę i prepy”, którego jeszcze
    # nie ma w kalendarzu (przełożenie czeka na DL-a). Treść zaproszenia
    # kandydata podaje ten termin, nie starą rozmowę (decyzja Artura
    # 22.10.2026, audyt F37).
    interview_start: Optional[datetime] = None

    @model_validator(mode="after")
    def _window(self) -> "PrepCreate":
        if self.end <= self.start:
            raise ValueError("Koniec prepu musi być późniejszy niż jego początek.")
        return self


class PrepUpdate(BaseModel):
    """Zmiana prepu. Pola puste zostają; ``attendee_*`` podane = pełna nowa lista."""

    start: Optional[datetime] = None
    end: Optional[datetime] = None
    organizer_user_id: Optional[int] = None
    attendee_user_ids: Optional[list[int]] = Field(default=None, max_length=10)
    attendee_emails: Optional[list[EmailStr]] = Field(default=None, max_length=10)
    client_request_id: Optional[str] = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _window(self) -> "PrepUpdate":
        if (self.start is None) != (self.end is None):
            raise ValueError("Podaj początek i koniec prepu.")
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("Koniec prepu musi być późniejszy niż jego początek.")
        return self


class PrepCancel(BaseModel):
    comment: Optional[str] = Field(default=None, max_length=500)


class ReviewOut(BaseModel):
    status: str
    level: Optional[str] = None
    coverage: Optional[float] = None
    criteria: dict
    summary: Optional[str] = None
    remaining: list
    # 0505: wersja Ustawienia → Ocena prepów (NULL = startowe) i promptu.
    config_version: Optional[int] = None
    prompt_version: Optional[str] = None


class PrepOut(BaseModel):
    event_id: int
    prep_no: int
    candidate_id: int
    job_id: int
    organizer: Optional[PersonOut] = None
    scheduled_by: Optional[PersonOut] = None
    attendees: list[AttendeeOut] = []
    status: str = "scheduled"
    can_edit: bool = False
    # Odpowiedź kandydata z Outlooka prowadzącego (0453): none | accepted |
    # tentative | declined; NULL = jeszcze nie sprawdzano.
    candidate_response: Optional[str] = None
    candidate_response_at: Optional[datetime] = None
    proposed_start: Optional[datetime] = None
    proposed_end: Optional[datetime] = None
    start: datetime
    end: Optional[datetime] = None
    online_meeting_url: Optional[str] = None
    transcription_setup: str
    transcript_status: str
    talk_share: Optional[float] = None
    duration_seconds: Optional[int] = None
    review: Optional[ReviewOut] = None


class CueOut(BaseModel):
    """Wypowiedź z VTT: sekunda od początku, mówca i jego rola w prepie."""

    start: int
    speaker: Optional[str] = None
    # staff | candidate | unknown; None = Teams nie podał mówcy
    role: Optional[str] = None
    text: str


class TranscriptOut(BaseModel):
    event_id: int
    speakers: list
    text: str
    fetched_at: datetime
    cues: list[CueOut] = []


def _cues(transcript: PrepTranscript) -> list[CueOut]:
    roles = {
        s.get("name"): s.get("role")
        for s in (transcript.speakers or [])
        if isinstance(s, dict)
    }
    return [
        CueOut(
            start=int(cue.start),
            speaker=cue.speaker,
            role=roles.get(cue.speaker) if cue.speaker else None,
            text=cue.text,
        )
        for cue in teams_vtt.parse_vtt(transcript.vtt or "")
    ]


async def _people(db: AsyncSession, ids: list[int]) -> dict[int, PersonOut]:
    if not ids:
        return {}
    rows = await db.execute(
        select(User.id, User.name).where(User.id.in_(ids), User.is_active.is_(True))
    )
    return {uid: PersonOut(id=uid, name=name) for uid, name in rows.all()}


async def _invitable_people(db: AsyncSession, team_ids: set[int]) -> list[PersonOption]:
    """Wszyscy aktywni z adresem e-mail — zespół rekrutacji na górze (D1)."""
    rows = await db.execute(
        select(User.id, User.name, User.role).where(
            User.is_active.is_(True), User.email.isnot(None), User.email != ""
        )
    )
    people = [
        PersonOption(
            id=uid,
            name=name,
            role=role.value if role is not None else None,
            in_team=uid in team_ids,
        )
        for uid, name, role in rows.all()
        if name
    ]
    return sorted(people, key=lambda p: (not p.in_team, p.name.lower()))


async def _active_users(db: AsyncSession, ids: set[int]) -> dict[int, User]:
    if not ids:
        return {}
    return {
        u.id: u
        for u in (
            await db.scalars(
                select(User).where(User.id.in_(ids), User.is_active.is_(True))
            )
        ).all()
    }


async def _attendee_users(db: AsyncSession, ids: list[int]) -> list[User]:
    """Zaproszeni z NEXUSA: aktywni, z adresem. Inaczej 422 (nie cicho pomijamy)."""
    found = await _active_users(db, set(ids))
    missing = [i for i in ids if i not in found or not found[i].email]
    if missing:
        raise HTTPException(
            status_code=422,
            detail="Część zaproszonych osób jest nieaktywna albo nie ma adresu "
            "e-mail w NEXUSIE — usuń je z listy.",
        )
    return [found[i] for i in dict.fromkeys(ids)]


async def _organizer_allowed(
    db: AsyncSession, *, job: Job, candidate_id: int, prep_no: int
) -> set[int]:
    """Prowadzić może zespół rekrutacji albo podpowiadana osoba — ich skrzynki
    są w grupie, w której aplikacja zakłada spotkania."""
    allowed = set(await list_job_member_ids(db, job.id))
    suggested = await prep_meetings.suggest_organizer_id(
        db, job=job, candidate_id=candidate_id, prep_no=prep_no
    )
    if suggested:
        allowed.add(suggested)
    return allowed


@router.get("/interview-cycle/preps/options", response_model=PrepOptionsOut)
async def prep_options(
    current_user: CalendarWriteAccess,
    candidate_id: int = Query(...),
    job_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
) -> PrepOptionsOut:
    await ensure_job_membership(db, current_user, job_id)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    suggested_ids = await prep_meetings.suggestion_summary(
        db, job=job, candidate_id=candidate_id
    )
    member_ids = await list_job_member_ids(db, job_id)
    team_ids = {*member_ids, *[i for i in suggested_ids.values() if i]}
    people = await _people(db, sorted(team_ids))
    # Nazwisko w podglądzie tytułu tylko dla ról czytających kandydatów —
    # jak na ekranie „Rozmowy u klienta” (``load_overview``).
    candidate = (
        await db.get(Candidate, candidate_id)
        if user_has_candidate_read(current_user)
        else None
    )
    client_name = await _client_name(db, job)
    interview_start = await prep_meetings.upcoming_interview_start(
        db, candidate_id=candidate_id, job_id=job_id
    )
    who = prep_meetings.candidate_name(candidate) if candidate else "Kandydat"
    role = await cv_role_title_for_job(db, job)
    prep1 = await prep_review.latest_prep1_review(
        db, candidate_id=candidate_id, job_id=job_id
    )
    return PrepOptionsOut(
        prep1_followup=[
            PrepFollowupOut(
                key=str(f["key"]),
                label=str(f["label"]),
                reason=f.get("reason"),
                note=f.get("note"),
            )
            for f in prep_review.prep1_followup_of(prep1)
        ],
        enabled=prep_meetings.app_only_ready(),
        auto_transcribe=bool(settings.TEAMS_PREP_AUTO_TRANSCRIBE),
        suggested={
            n: people.get(uid) if uid else None for n, uid in suggested_ids.items()
        },
        team=sorted(people.values(), key=lambda p: p.name.lower()),
        people=await _invitable_people(db, team_ids),
        notice=prep_invitation.NOTICE_TEXT,
        invitation={
            n: InvitationPreviewOut(
                title=prep_invitation.title(n, who, client_name),
                body=prep_invitation.text(
                    prep_no=n,
                    client_name=client_name,
                    job_title=role,
                    interview_start=interview_start,
                    note=prep_invitation.NOTE_FIELD,
                    organizer_name=prep_invitation.ORGANIZER_FIELD,
                ),
                interview_line=(
                    prep_invitation.interview_line(interview_start)
                    if interview_start is not None
                    else None
                ),
            )
            for n in (1, 2)
        },
    )


class PrepOptionTime(BaseModel):
    start: datetime
    end: datetime


class PrepSuggestion(BaseModel):
    prep_no: int
    organizer: Optional[PersonOut] = None
    # ok — zajętość z kalendarza prowadzącego; unavailable — aplikacja go nie
    # czyta (spoza grupy, błąd); off — prepy w Teams wyłączone.
    calendar: Literal["ok", "unavailable", "off"]
    # Prep tej rundy już jest — podpowiedzi nie ma, ekran pokazuje termin.
    scheduled_start: Optional[datetime] = None
    minutes: int
    options: list[PrepOptionTime]
    # Zajęte bloki prowadzącego od teraz do rozmowy — dla „Inna godzina…”
    # (22.10.2026). Puste, gdy kalendarza nie widać (`calendar` mówi dlaczego).
    busy: list[PrepOptionTime] = Field(default_factory=list)


class PrepSuggestionsOut(BaseModel):
    enabled: bool
    preps: list[PrepSuggestion]


def _hhmm(value: Optional[str]) -> Optional[time]:
    if not value:
        return None
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        raise HTTPException(
            status_code=422, detail="Godzina w formacie GG:MM."
        ) from None
    return parsed.replace(second=0, microsecond=0)


@router.get("/interview-cycle/preps/suggestions", response_model=PrepSuggestionsOut)
async def prep_suggestions(
    current_user: CalendarWriteAccess,
    candidate_id: int = Query(...),
    job_id: int = Query(...),
    interview_start: datetime = Query(...),
    candidate_from: Optional[str] = Query(None, max_length=5),
    candidate_to: Optional[str] = Query(None, max_length=5),
    db: AsyncSession = Depends(get_db),
) -> PrepSuggestionsOut:
    """Wolne godziny Prepu 1 i Prepu 2 przed wybieraną rozmową (20.10.2026).

    Niczego nie zapisuje. Zajętość z kalendarzy prowadzących przez aplikację
    prepów (``prep_availability``); bez niej godziny liczą się bez kalendarza.
    """
    await ensure_job_membership(db, current_user, job_id)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    now = datetime.now(timezone.utc)
    if interview_start.tzinfo is None:
        interview_start = interview_start.replace(tzinfo=timezone.utc)
    if interview_start <= now:
        raise HTTPException(status_code=422, detail="Rozmowa musi być w przyszłości.")
    if interview_start > now + timedelta(days=120):
        raise HTTPException(
            status_code=422, detail="Rozmowa jest za daleko w przyszłości."
        )
    cand_from, cand_to = _hhmm(candidate_from), _hhmm(candidate_to)
    windows = None
    if cand_from or cand_to:
        lo, hi = (
            cand_from or prep_availability.WORK_START,
            cand_to or prep_availability.LATE_END,
        )
        if hi <= lo:
            raise HTTPException(
                status_code=422,
                detail="Koniec okna kandydata musi być po jego początku.",
            )
        windows = [(lo, hi)]

    suggested = await prep_meetings.suggestion_summary(
        db, job=job, candidate_id=candidate_id
    )
    organizer_ids = {uid for uid in suggested.values() if uid}
    users = await _active_users(db, organizer_ids)
    enabled = prep_meetings.app_only_ready()
    emails = [u.email for u in users.values() if u.email]
    busy = (
        await prep_availability.busy_blocks(
            emails, start=now, end=interview_start + timedelta(hours=1)
        )
        if enabled
        else {}
    )

    out: list[PrepSuggestion] = []
    avoid: list[tuple[datetime, datetime]] = []
    # Oba zaplanowane prepy omijamy od początku — zaplanowany Prep 2 nie może
    # dostać Prepu 1 w tej samej godzinie (audyt 22.10, F34).
    scheduled: dict[int, Optional[CalendarEvent]] = {}
    for prep_no in (1, 2):
        existing = await prep_meetings.active_prep(
            db, candidate_id=candidate_id, job_id=job_id, prep_no=prep_no
        )
        event = (
            await db.get(CalendarEvent, existing.calendar_event_id)
            if existing
            else None
        )
        scheduled[prep_no] = event
        if event is not None:
            avoid.append((event.start_time, event.end_time))
    for prep_no in (1, 2):
        uid = suggested.get(prep_no)
        user = users.get(uid) if uid else None
        event = scheduled[prep_no]
        user_busy = busy.get((user.email or "").lower()) if user else None
        calendar: Literal["ok", "unavailable", "off"] = (
            "off" if not enabled else ("ok" if user_busy is not None else "unavailable")
        )
        options = (
            []
            if event is not None
            else prep_availability.suggest(
                prep_no=prep_no,
                interview_start=interview_start,
                now=now,
                busy=user_busy,
                candidate_windows=windows,
                avoid=avoid,
            )
        )
        if options and event is None:
            # Prep 2 nie podpowiada godziny polecanego Prepu 1.
            avoid.append((options[0].start, options[0].end))
        out.append(
            PrepSuggestion(
                prep_no=prep_no,
                organizer=PersonOut(id=user.id, name=user.name or user.email)
                if user
                else None,
                calendar=calendar,
                scheduled_start=event.start_time if event is not None else None,
                minutes=prep_availability.PREP_MINUTES,
                options=[PrepOptionTime(start=o.start, end=o.end) for o in options],
                busy=[PrepOptionTime(start=s, end=e) for s, e in user_busy or []],
            )
        )
    return PrepSuggestionsOut(enabled=enabled, preps=out)


@router.post(
    "/interview-cycle/preps",
    response_model=PrepOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_prep(
    body: PrepCreate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> PrepOut:
    if not prep_meetings.app_only_ready():
        raise HTTPException(
            status_code=503,
            detail="Planowanie prepów w Teams nie jest jeszcze włączone.",
        )
    await ensure_job_membership(db, current_user, body.job_id)
    job = await db.get(Job, body.job_id)
    candidate = await db.get(Candidate, body.candidate_id)
    if job is None or candidate is None:
        raise HTTPException(
            status_code=404, detail="Nie znaleziono rekrutacji albo kandydata."
        )
    if not await interview_slots.pair_in_pipeline(
        db, candidate_id=candidate.id, job_id=job.id
    ):
        raise HTTPException(
            status_code=422, detail="Kandydat nie jest w pipeline tej rekrutacji."
        )
    existing = await prep_meetings.active_prep(
        db, candidate_id=candidate.id, job_id=job.id, prep_no=body.prep_no
    )
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PREP_ALREADY_SCHEDULED",
                "event_id": existing.calendar_event_id,
                "message": await prep_meetings.already_scheduled_message(db, existing),
            },
        )

    # Zaprosić można każdego (D1, 17.10.2026); prowadzący dalej musi być
    # z zespołu albo z podpowiedzi.
    allowed = await _organizer_allowed(
        db, job=job, candidate_id=candidate.id, prep_no=body.prep_no
    )
    if body.organizer_user_id not in allowed:
        raise HTTPException(
            status_code=422,
            detail="Prep prowadzi ktoś z zespołu tej rekrutacji.",
        )
    organizer = (await _active_users(db, {body.organizer_user_id})).get(
        body.organizer_user_id
    )
    if organizer is None:
        raise HTTPException(status_code=422, detail="Organizator jest nieaktywny.")
    attendees = await _attendee_users(
        db, [i for i in body.attendee_user_ids if i != organizer.id]
    )
    # Kalendarz prowadzącego jeszcze raz tuż przed zapisem (22.10.2026): między
    # otwarciem okna a kliknięciem godzinę mógł zająć ktoś inny, a godzina
    # wpisana ręcznie mogła od początku wpadać na „zajęte”.
    nexus_preps = await prep_meetings.organizer_prep_spans(
        db, organizer_id=organizer.id, start=body.start, end=body.end
    )
    blocks: dict = {}
    if organizer.email:
        blocks = await prep_availability.busy_blocks(
            [organizer.email], start=body.start, end=body.end
        )
    clash = prep_availability.busy_overlap(
        body.start,
        body.end,
        blocks.get((organizer.email or "").strip().lower()),
        nexus_preps=nexus_preps,
    )
    if clash is not None and not body.accept_busy:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "PREP_SLOT_BUSY",
                "busy_start": clash[0].isoformat(),
                "busy_end": clash[1].isoformat(),
                "message": (
                    f"{organizer.name or organizer.email} ma wtedy zajęte "
                    f"({prep_availability.span_label(clash)}). Wybierz inną "
                    "godzinę albo zapisz mimo to, jeśli to uzgodnione."
                ),
            },
        )

    created = await prep_meetings.create_prep(
        db,
        actor=current_user,
        candidate=candidate,
        job=job,
        prep_no=body.prep_no,
        organizer=organizer,
        start=body.start,
        end=body.end,
        extra_attendees=attendees,
        note=body.note,
        client_request_id=body.client_request_id,
        client_name=await _client_name(db, job),
        extra_emails=[str(e) for e in body.attendee_emails],
        interview_start=body.interview_start,
    )
    # Prep w cudzym kalendarzu albo dla kandydata innej osoby z pary (D6).
    await prep_notifications.notify_prep_change(
        db,
        actor=current_user,
        prep=created.prep,
        event=created.event,
        kind="scheduled",
        clash=clash,
    )
    if body.prep_no == 2:
        # 0482: Prep 2 jednak jest — zapisane „bez Prepu 2” przestaje obowiązywać.
        await prep2_skips.clear_upcoming(db, candidate_id=candidate.id, job_id=job.id)
    await db.commit()
    return await _prep_out(db, created.prep, created.event, current_user)


async def _load(db: AsyncSession, event_id: int) -> tuple[PrepMeeting, CalendarEvent]:
    prep = await prep_meetings.prep_for_event(db, event_id)
    event = await db.get(CalendarEvent, event_id) if prep else None
    if prep is None or event is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono prepu.")
    return prep, event


async def _attendees_out(
    db: AsyncSession, event: CalendarEvent, candidate_email: Optional[str]
) -> list[AttendeeOut]:
    skip = {(candidate_email or "").lower()}
    emails = [
        e
        for e in dict.fromkeys(_attendee_emails(event.attendees))
        if e.lower() not in skip
    ]
    if not emails:
        return []
    users = {
        email.lower(): (uid, name)
        for uid, name, email in (
            await db.execute(
                select(User.id, User.name, User.email).where(
                    func.lower(User.email).in_([e.lower() for e in emails])
                )
            )
        ).all()
        if email
    }
    out = []
    for email in emails:
        uid, name = users.get(email.lower(), (None, None))
        out.append(AttendeeOut(email=email, user_id=uid, name=name))
    return out


async def _prep_out(
    db: AsyncSession,
    prep: PrepMeeting,
    event: CalendarEvent,
    viewer: Optional[User] = None,
) -> PrepOut:
    transcript = await db.scalar(
        select(PrepTranscript).where(PrepTranscript.prep_meeting_id == prep.id)
    )
    review = await db.scalar(
        select(PrepReview).where(PrepReview.prep_meeting_id == prep.id)
    )
    people = await _people(
        db, [i for i in (prep.organizer_user_id, prep.scheduled_by_user_id) if i]
    )
    candidate_email = await db.scalar(
        select(Candidate.email).where(Candidate.id == prep.candidate_id)
    )
    can_edit = False
    if viewer is not None and event.status != EventStatus.cancelled:
        job = await db.get(Job, prep.job_id)
        can_edit = prep_meetings.user_can_edit_prep(
            viewer, await prep_meetings.prep_editor_ids(db, prep, job)
        )
    return PrepOut(
        event_id=event.id,
        prep_no=prep.prep_no,
        candidate_id=prep.candidate_id,
        job_id=prep.job_id,
        organizer=people.get(prep.organizer_user_id or 0),
        scheduled_by=people.get(prep.scheduled_by_user_id or 0),
        attendees=await _attendees_out(db, event, candidate_email),
        status=event.status.value if event.status is not None else "scheduled",
        can_edit=can_edit,
        candidate_response=prep.candidate_response,
        candidate_response_at=prep.candidate_response_at,
        proposed_start=prep.proposed_start,
        proposed_end=prep.proposed_end,
        start=event.start_time,
        end=event.end_time,
        online_meeting_url=event.online_meeting_url,
        transcription_setup=prep.transcription_setup,
        transcript_status=prep.transcript_status,
        talk_share=float(transcript.talk_share)
        if transcript and transcript.talk_share is not None
        else None,
        duration_seconds=transcript.duration_seconds if transcript else None,
        review=ReviewOut(
            status=review.status,
            level=review.level,
            coverage=float(review.coverage) if review.coverage is not None else None,
            criteria=review.criteria or {},
            summary=review.summary,
            remaining=review.remaining or [],
            config_version=review.config_version,
            prompt_version=review.prompt_version,
        )
        if review
        else None,
    )


@router.get("/interview-cycle/preps/{event_id}", response_model=PrepOut)
async def get_prep(
    event_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> PrepOut:
    prep, event = await _load(db, event_id)
    await ensure_job_read_access(db, current_user, prep.job_id)
    return await _prep_out(db, prep, event, current_user)


async def _editable(
    db: AsyncSession, event_id: int, user: User
) -> tuple[PrepMeeting, CalendarEvent, Job]:
    prep, event = await _load(db, event_id)
    await ensure_job_read_access(db, user, prep.job_id)
    job = await db.get(Job, prep.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    if not prep_meetings.user_can_edit_prep(
        user, await prep_meetings.prep_editor_ids(db, prep, job)
    ):
        raise HTTPException(
            status_code=403,
            detail="Ten prep mogą zmienić: prowadzący, Delivery Lead rekrutacji, "
            "rekruter kandydata i osoba, która go zaplanowała.",
        )
    return prep, event, job


@router.patch("/interview-cycle/preps/{event_id}", response_model=PrepOut)
async def update_prep(
    event_id: int,
    body: PrepUpdate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> PrepOut:
    """Nowy termin, zaproszeni albo prowadzący prepu (17.10.2026, D1–D4).

    Zmienia każdy z ludzi pary (``user_can_edit_prep``), nie tylko prowadzący:
    rekruter planuje Prep 1 w kalendarzu DL-a i to do niego kandydat pisze,
    że termin mu nie pasuje.
    """
    prep, event, job = await _editable(db, event_id, current_user)
    prep_meetings.ensure_prep_open(event)
    candidate = await db.get(Candidate, prep.candidate_id)
    if candidate is None or not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="Kandydat nie ma adresu e-mail — nie da się wysłać zmiany.",
        )
    start = body.start or event.start_time
    end = body.end or event.end_time
    attendees_changed = body.attendee_user_ids is not None or (
        body.attendee_emails is not None
    )
    if attendees_changed:
        users = await _attendee_users(db, body.attendee_user_ids or [])
        emails = [str(e) for e in body.attendee_emails or []]
    else:
        users = []
        emails = [a.email for a in await _attendees_out(db, event, candidate.email)]

    if (
        body.organizer_user_id is not None
        and body.organizer_user_id != prep.organizer_user_id
    ):
        allowed = await _organizer_allowed(
            db, job=job, candidate_id=candidate.id, prep_no=prep.prep_no
        )
        organizer = (await _active_users(db, {body.organizer_user_id})).get(
            body.organizer_user_id
        )
        if body.organizer_user_id not in allowed or organizer is None:
            raise HTTPException(
                status_code=422,
                detail="Prep prowadzi aktywna osoba z zespołu tej rekrutacji.",
            )
        created = await prep_meetings.replace_organizer(
            db,
            actor=current_user,
            prep=prep,
            event=event,
            candidate=candidate,
            job=job,
            organizer=organizer,
            start=start,
            end=end,
            users=[u for u in users if u.id != organizer.id],
            emails=emails,
            client_request_id=body.client_request_id,
            client_name=await _client_name(db, job),
        )
        record_calendar_audit(
            db,
            action=CALENDAR_EVENT_CANCELLED,
            user_id=current_user.id,
            event_id=event.id,
            override=user_is_override(current_user),
            details={"replaced_by": created.event.id, "reason": "organizer_changed"},
        )
        await prep_notifications.notify_prep_change(
            db,
            actor=current_user,
            prep=created.prep,
            event=created.event,
            kind="organizer",
            previous_organizer_id=prep.organizer_user_id,
        )
        await db.commit()
        return await _prep_out(db, created.prep, created.event, current_user)

    moved = body.start is not None and (
        _aware(body.start) != _aware(event.start_time)
        or _aware(body.end) != _aware(event.end_time)
    )
    new_list = (
        prep_meetings.attendee_emails(
            candidate_email=candidate.email,
            organizer_email=prep.organizer_upn,
            users=users,
            emails=emails,
        )
        if attendees_changed
        else None
    )
    if new_list is not None and [a.lower() for a in new_list] == [
        a.lower() for a in _attendee_emails(event.attendees)
    ]:
        new_list = None
    if not moved and new_list is None:
        return await _prep_out(db, prep, event, current_user)
    previous_start = event.start_time
    await prep_meetings.push_prep_update(
        prep,
        event,
        start=start if moved else None,
        end=end if moved else None,
        attendees=new_list,
    )
    record_calendar_audit(
        db,
        action=CALENDAR_EVENT_UPDATED,
        user_id=current_user.id,
        event_id=event.id,
        override=user_is_override(current_user),
        details={"moved": moved, "attendees": new_list is not None},
    )
    await prep_notifications.notify_prep_change(
        db,
        actor=current_user,
        prep=prep,
        event=event,
        kind="moved" if moved else "attendees",
        previous_start=previous_start,
    )
    await db.commit()
    return await _prep_out(db, prep, event, current_user)


@router.post("/interview-cycle/preps/{event_id}/cancel", response_model=PrepOut)
async def cancel_prep(
    event_id: int,
    body: PrepCancel,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> PrepOut:
    """Odwołanie prepu przez kogoś z pary — kandydat dostaje odwołanie od
    prowadzącego. Drugi raz to samo = bez zmian."""
    prep, event, _job = await _editable(db, event_id, current_user)
    if event.status == EventStatus.cancelled:
        return await _prep_out(db, prep, event, current_user)
    prep_meetings.ensure_prep_open(event)
    outlook = await prep_meetings.cancel_prep(prep, event, body.comment)
    record_calendar_audit(
        db,
        action=CALENDAR_EVENT_CANCELLED,
        user_id=current_user.id,
        event_id=event.id,
        override=user_is_override(current_user),
        details={"outlook": outlook},
    )
    await prep_notifications.notify_prep_change(
        db, actor=current_user, prep=prep, event=event, kind="cancelled"
    )
    await db.commit()
    return await _prep_out(db, prep, event, current_user)


@router.get(
    "/interview-cycle/preps/{event_id}/transcript", response_model=TranscriptOut
)
async def get_prep_transcript(
    event_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> TranscriptOut:
    prep, _event = await _load(db, event_id)
    await ensure_job_read_access(db, current_user, prep.job_id)
    transcript = await db.scalar(
        select(PrepTranscript).where(PrepTranscript.prep_meeting_id == prep.id)
    )
    if transcript is None:
        raise HTTPException(status_code=404, detail="Transkryptu jeszcze nie ma.")
    logger.info("prep transcript read: event=%s user=%s", event_id, current_user.id)
    return TranscriptOut(
        event_id=event_id,
        speakers=transcript.speakers or [],
        text=transcript.plain_text,
        fetched_at=transcript.fetched_at,
        cues=_cues(transcript),
    )


# ── Raport jakości prepów (Head of Recruitment) ──────────────────────────────


class PrepQualityRow(BaseModel):
    organizer: PersonOut
    preps: int
    recorded: int
    unrecorded: int
    good: int
    ok: int
    weak: int
    avg_talk_share: Optional[float] = None


class Prep2SkipRow(BaseModel):
    """Rozmowy u klienta osoby (właściciel rozmowy) bez Prepu 2 (0482)."""

    person: PersonOut
    interviews: int
    with_reason: int
    silent: int
    # Zapisane po fakcie — osobno, nie „bez słowa” (audyt 22.10.2026, F28).
    after_the_fact: int = 0
    share: float
    over_threshold: bool
    reasons: dict[str, int] = {}


class PrepQualityOut(BaseModel):
    days: int
    rows: list[PrepQualityRow]
    # Rozmowy w kalendarzu przed swoim startem; zapisane po fakcie są osobno
    # (``interviews_after_the_fact``) i nie zaniżają linii o dwóch prepach
    # (decyzja Artura 22.10.2026, audyt F28).
    interviews: int
    interviews_with_two_preps: int
    interviews_after_the_fact: int = 0
    # 0482: rozmowy bez Prepu 2 w ostatnich ``skip_days`` dniach per osoba.
    skip_days: int = prep2_skips.STATS_WINDOW_DAYS
    skip_threshold: float = prep2_skips.THRESHOLD_SHARE
    skip_rows: list[Prep2SkipRow] = []


@router.get("/interview-cycle/prep-quality", response_model=PrepQualityOut)
async def prep_quality_report(
    current_user: RecruitmentReadAccess,
    days: int = Query(90, ge=7, le=365),
    db: AsyncSession = Depends(get_db),
) -> PrepQualityOut:
    """Prepy z NEXUSA w ostatnich ``days`` dniach per organizator.

    Tylko admin i Head of Recruitment — raport ocenia pracę konkretnych osób.
    """
    from datetime import timedelta, timezone as _tz

    from sqlalchemy import func

    from app.models.calendar_event import EventStatus, EventType
    from app.models.user import UserRole

    if not current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        raise HTTPException(
            status_code=403,
            detail="Raport jakości prepów jest dla Head of Recruitment.",
        )
    now = datetime.now(_tz.utc)
    since = now - timedelta(days=days)
    rows = (
        await db.execute(
            select(
                PrepMeeting.organizer_user_id,
                func.count(PrepMeeting.id),
                func.count(PrepTranscript.id),
                func.count().filter(PrepMeeting.transcript_status == "missing"),
                func.count().filter(PrepReview.level == "good"),
                func.count().filter(PrepReview.level == "ok"),
                func.count().filter(PrepReview.level == "weak"),
                func.avg(PrepTranscript.talk_share),
            )
            .join(CalendarEvent, CalendarEvent.id == PrepMeeting.calendar_event_id)
            .outerjoin(PrepTranscript, PrepTranscript.prep_meeting_id == PrepMeeting.id)
            .outerjoin(PrepReview, PrepReview.prep_meeting_id == PrepMeeting.id)
            .where(
                CalendarEvent.start_time >= since,
                CalendarEvent.start_time <= now,
                CalendarEvent.status != EventStatus.cancelled,
                PrepMeeting.organizer_user_id.isnot(None),
            )
            .group_by(PrepMeeting.organizer_user_id)
        )
    ).all()
    people = await _people(db, [r[0] for r in rows])

    interviews = (
        await db.execute(
            select(
                CalendarEvent.candidate_id,
                CalendarEvent.job_id,
                CalendarEvent.start_time,
                CalendarEvent.created_at,
            ).where(
                CalendarEvent.event_type == EventType.client_interview,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time >= since,
                CalendarEvent.start_time <= now,
                CalendarEvent.candidate_id.isnot(None),
                CalendarEvent.job_id.isnot(None),
            )
        )
    ).all()
    by_pair: dict[tuple[int, int], list[datetime]] = {}
    if interviews:
        prep_rows = (
            await db.execute(
                select(
                    CalendarEvent.candidate_id,
                    CalendarEvent.job_id,
                    CalendarEvent.start_time,
                ).where(
                    CalendarEvent.event_type == EventType.prep_call,
                    CalendarEvent.status != EventStatus.cancelled,
                    CalendarEvent.start_time >= since - timedelta(days=30),
                    CalendarEvent.candidate_id.in_({iv[0] for iv in interviews}),
                )
            )
        ).all()
        for c, j, s in prep_rows:
            by_pair.setdefault((c, j), []).append(s)
    counted, preps_before, after_the_fact = prep2_skips.tally_two_preps(
        interviews, by_pair
    )

    return PrepQualityOut(
        days=days,
        rows=sorted(
            (
                PrepQualityRow(
                    organizer=people.get(uid) or PersonOut(id=uid, name=f"#{uid}"),
                    preps=total,
                    recorded=recorded,
                    unrecorded=unrecorded,
                    good=good,
                    ok=ok,
                    weak=weak,
                    avg_talk_share=round(float(avg), 3) if avg is not None else None,
                )
                for uid, total, recorded, unrecorded, good, ok, weak, avg in rows
            ),
            key=lambda r: (-r.preps, r.organizer.name.lower()),
        ),
        interviews=counted,
        interviews_with_two_preps=preps_before,
        interviews_after_the_fact=after_the_fact,
        skip_rows=await _skip_rows(db, now),
    )


async def _skip_rows(db: AsyncSession, now: datetime) -> list[Prep2SkipRow]:
    from datetime import timedelta

    stats = await prep2_skips.skip_stats(
        db,
        since=now - timedelta(days=prep2_skips.STATS_WINDOW_DAYS),
        until=now,
        now=now,
    )
    people = await _people(db, list(stats))
    rows = [
        Prep2SkipRow(
            person=people.get(uid) or PersonOut(id=uid, name=f"#{uid}"),
            interviews=stat.interviews,
            with_reason=stat.with_reason,
            silent=stat.silent,
            after_the_fact=stat.after_the_fact,
            share=round(stat.share, 3),
            over_threshold=stat.over_threshold,
            reasons=stat.reasons,
        )
        for uid, stat in stats.items()
    ]
    return sorted(
        rows, key=lambda r: (not r.over_threshold, -r.share, r.person.name.lower())
    )


# ── Rozmowa bez Prepu 2 (0482, 20.10.2026) ───────────────────────────────────


class Prep2SkipCreate(BaseModel):
    candidate_id: int
    job_id: int
    reason: Literal["no_slot", "short_notice", "prep1_covered", "other"]
    reason_note: Optional[str] = Field(default=None, max_length=500)
    call_at: datetime

    @model_validator(mode="after")
    def _other_needs_note(self) -> "Prep2SkipCreate":
        note = (self.reason_note or "").strip()
        self.reason_note = note or None
        if self.reason == "other" and not note:
            raise ValueError("Opisz powód — „Inny powód” wymaga kilku słów.")
        return self


class Prep2CallDone(BaseModel):
    note: Optional[str] = Field(default=None, max_length=2000)


class Prep2SkipOut(BaseModel):
    id: int
    interview_event_id: int
    candidate_id: int
    job_id: int
    reason: str
    reason_note: Optional[str] = None
    call_at: datetime
    call_done_at: Optional[datetime] = None
    call_note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime


def _skip_out(row: Prep2Skip) -> Prep2SkipOut:
    return Prep2SkipOut(
        id=row.id,
        interview_event_id=row.interview_event_id,
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        reason=row.reason,
        reason_note=row.reason_note,
        call_at=_aware(row.call_at),
        call_done_at=_aware(row.call_done_at),
        call_note=row.call_note,
        created_by=row.created_by,
        created_at=_aware(row.created_at) or datetime.now(timezone.utc),
    )


@router.post(
    "/interview-cycle/prep2-skip",
    response_model=Prep2SkipOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_prep2_skip(
    body: Prep2SkipCreate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> Prep2SkipOut:
    """Rozmowa bez Prepu 2 — tylko tuż przed rozmową, po odbytym Prepie 1.

    Te same bramki co planowanie prepu: kto może założyć Prep 2, ten może
    zapisać, że go nie będzie — z powodem i telefonem przed rozmową.
    """
    await ensure_job_membership(db, current_user, body.job_id)
    if not await interview_slots.pair_in_pipeline(
        db, candidate_id=body.candidate_id, job_id=body.job_id
    ):
        raise HTTPException(
            status_code=422, detail="Kandydat nie jest w pipeline tej rekrutacji."
        )
    now = datetime.now(timezone.utc)
    row = await prep2_skips.create_skip(
        db,
        actor=current_user,
        candidate_id=body.candidate_id,
        job_id=body.job_id,
        reason=body.reason,
        reason_note=body.reason_note,
        call_at=body.call_at,
        now=now,
    )
    interview = await db.get(CalendarEvent, row.interview_event_id)
    interview_start = _aware(interview.start_time) if interview else now
    await prep2_skips.notify_skip(
        db, actor=current_user, skip=row, interview_start=interview_start
    )
    owner_id = (
        (interview.operational_owner_id or interview.created_by) if interview else None
    )
    if owner_id:
        await prep2_skips.notify_threshold(
            db, owner_id=owner_id, until=max(interview_start, now), now=now
        )
    await db.commit()
    await db.refresh(row)
    logger.info(
        "prep2 skip: candidate=%s job=%s reason=%s user=%s",
        row.candidate_id,
        row.job_id,
        row.reason,
        current_user.id,
    )
    return _skip_out(row)


@router.post(
    "/interview-cycle/prep2-skip/{skip_id}/call-done", response_model=Prep2SkipOut
)
async def prep2_call_done(
    skip_id: int,
    body: Prep2CallDone,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> Prep2SkipOut:
    row = await db.get(Prep2Skip, skip_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono wpisu.")
    await ensure_job_membership(db, current_user, row.job_id)
    note = (body.note or "").strip() or None
    await prep2_skips.mark_call_done(db, actor=current_user, skip=row, note=note)
    await db.commit()
    await db.refresh(row)
    return _skip_out(row)
