"""Prepy w Teams (0370): planowanie Prep 1/2, transkrypt i ocena prepu.

* ``GET  /api/interview-cycle/preps/options`` — czy integracja działa,
  podpowiedzi organizatora dla obu prepów i zespół rekrutacji do wyboru.
* ``POST /api/interview-cycle/preps`` — zakłada prep w kalendarzu
  organizatora (Teams, zaproszenie kandydata, automatyczna transkrypcja).
* ``GET  /api/interview-cycle/preps/{event_id}`` — stan prepu i ocena.
* ``GET  /api/interview-cycle/preps/{event_id}/transcript`` — pełny transkrypt
  (zespół rekrutacji, jak każdy odczyt rekrutacji).
* ``GET  /api/interview-cycle/prep-quality`` — raport jakości prepów per
  organizator (admin i Head of Recruitment).

Sekcja Pipeline + role zapisu kalendarza + członkostwo w rekrutacji — te same
bramki co pozostałe trasy „Rozmów u klienta”.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import (
    CalendarWriteAccess,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_job_read_access,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.prep_meeting import PrepMeeting, PrepReview, PrepTranscript
from app.models.user import User
from app.services import interview_slots, prep_meetings
from app.services.job_membership import list_job_member_ids

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class PersonOut(BaseModel):
    id: int
    name: str


class PrepOptionsOut(BaseModel):
    enabled: bool
    auto_transcribe: bool
    suggested: dict[int, Optional[PersonOut]]
    team: list[PersonOut]
    notice: str


class PrepCreate(BaseModel):
    candidate_id: int
    job_id: int
    prep_no: Literal[1, 2]
    organizer_user_id: int
    start: datetime
    end: datetime
    attendee_user_ids: list[int] = Field(default_factory=list, max_length=10)
    note: Optional[str] = Field(default=None, max_length=2000)
    client_request_id: Optional[str] = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def _window(self) -> "PrepCreate":
        if self.end <= self.start:
            raise ValueError("Koniec prepu musi być późniejszy niż jego początek.")
        return self


class ReviewOut(BaseModel):
    status: str
    level: Optional[str] = None
    coverage: Optional[float] = None
    criteria: dict
    summary: Optional[str] = None
    remaining: list


class PrepOut(BaseModel):
    event_id: int
    prep_no: int
    candidate_id: int
    job_id: int
    organizer: Optional[PersonOut] = None
    start: datetime
    end: Optional[datetime] = None
    online_meeting_url: Optional[str] = None
    transcription_setup: str
    transcript_status: str
    talk_share: Optional[float] = None
    duration_seconds: Optional[int] = None
    review: Optional[ReviewOut] = None


class TranscriptOut(BaseModel):
    event_id: int
    speakers: list
    text: str
    fetched_at: datetime


async def _people(db: AsyncSession, ids: list[int]) -> dict[int, PersonOut]:
    if not ids:
        return {}
    rows = await db.execute(
        select(User.id, User.name).where(User.id.in_(ids), User.is_active.is_(True))
    )
    return {uid: PersonOut(id=uid, name=name) for uid, name in rows.all()}


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
    people = await _people(
        db, sorted({*member_ids, *[i for i in suggested_ids.values() if i]})
    )
    return PrepOptionsOut(
        enabled=prep_meetings.app_only_ready(),
        auto_transcribe=bool(settings.TEAMS_PREP_AUTO_TRANSCRIBE),
        suggested={
            n: people.get(uid) if uid else None for n, uid in suggested_ids.items()
        },
        team=sorted(people.values(), key=lambda p: p.name.lower()),
        notice=prep_meetings.PREP_NOTICE_TEXT,
    )


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
                "message": f"Prep {body.prep_no} jest już zaplanowany — "
                "zmień jego termin albo go odwołaj.",
            },
        )

    allowed = set(await list_job_member_ids(db, job.id))
    suggested = await prep_meetings.suggest_organizer_id(
        db, job=job, candidate_id=candidate.id, prep_no=body.prep_no
    )
    if suggested:
        allowed.add(suggested)
    wanted = {body.organizer_user_id, *body.attendee_user_ids}
    if not wanted <= allowed:
        raise HTTPException(
            status_code=422,
            detail="Organizator i uczestnicy prepu muszą należeć do zespołu tej rekrutacji.",
        )
    users = {
        u.id: u
        for u in (
            await db.scalars(
                select(User).where(User.id.in_(wanted), User.is_active.is_(True))
            )
        ).all()
    }
    organizer = users.get(body.organizer_user_id)
    if organizer is None:
        raise HTTPException(status_code=422, detail="Organizator jest nieaktywny.")

    created = await prep_meetings.create_prep(
        db,
        actor=current_user,
        candidate=candidate,
        job=job,
        prep_no=body.prep_no,
        organizer=organizer,
        start=body.start,
        end=body.end,
        extra_attendees=[users[i] for i in body.attendee_user_ids if i in users],
        note=body.note,
        client_request_id=body.client_request_id,
    )
    await db.commit()
    return await _prep_out(db, created.prep, created.event)


async def _load(db: AsyncSession, event_id: int) -> tuple[PrepMeeting, CalendarEvent]:
    prep = await prep_meetings.prep_for_event(db, event_id)
    event = await db.get(CalendarEvent, event_id) if prep else None
    if prep is None or event is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono prepu.")
    return prep, event


async def _prep_out(
    db: AsyncSession, prep: PrepMeeting, event: CalendarEvent
) -> PrepOut:
    transcript = await db.scalar(
        select(PrepTranscript).where(PrepTranscript.prep_meeting_id == prep.id)
    )
    review = await db.scalar(
        select(PrepReview).where(PrepReview.prep_meeting_id == prep.id)
    )
    people = await _people(
        db, [prep.organizer_user_id] if prep.organizer_user_id else []
    )
    return PrepOut(
        event_id=event.id,
        prep_no=prep.prep_no,
        candidate_id=prep.candidate_id,
        job_id=prep.job_id,
        organizer=people.get(prep.organizer_user_id or 0),
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
    return await _prep_out(db, prep, event)


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


class PrepQualityOut(BaseModel):
    days: int
    rows: list[PrepQualityRow]
    interviews: int
    interviews_with_two_preps: int


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
    preps_before = 0
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
                    CalendarEvent.candidate_id.in_({c for c, _j, _s in interviews}),
                )
            )
        ).all()
        by_pair: dict[tuple[int, int], list[datetime]] = {}
        for c, j, s in prep_rows:
            by_pair.setdefault((c, j), []).append(s)
        preps_before = sum(
            1
            for c, j, start in interviews
            if sum(1 for s in by_pair.get((c, j), []) if s <= start) >= 2
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
        interviews=len(interviews),
        interviews_with_two_preps=preps_before,
    )
