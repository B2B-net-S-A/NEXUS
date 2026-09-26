"""Router `/api/candidate-followups` — follow-up z kandydatem, gdy klient milczy.

Kto dzwoni i kiedy liczy ``services/candidate_followups.py`` (przy odczycie).
Tu tylko odczyt stanu jednego kandydata i zapis wyniku telefonu:

- ``connected`` / ``changed`` zapisują JEDNĄ notatkę kandydata (typ „Rozmowa”,
  bez ``job_id``) — to ona zeruje zegar u wszystkich rekruterów naraz,
- ``changed`` wysyła dzwonek do właścicieli procesów, których zmiana dotyczy
  (etapu nie zmienia — decyduje właściciel procesu),
- ``no_answer`` / ``callback`` / ``claim`` zapisują sam wiersz dziennika.

Zapis dostaje każda rola operacyjna — rekrutacje i kandydatów widzą wszyscy
(decyzja Artura 23.09.2026).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_followup import CandidateFollowup
from app.models.calendar_event import CalendarEvent
from app.models.followup_meeting import FollowupMeeting
from app.models.call import Call, CallDirection
from app.models.note import Note, NoteType
from app.models.notification import NotificationType
from app.models.user import User
from app.models.user_activity import UserActionType, UserActivity
from app.services import candidate_followups as svc
from app.services import followup_meetings
from app.services.notification_triggers import emit

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Najdalej, na kiedy można umówić oddzwonienie — dalszy termin to już nie
# „oddzwoń później”, tylko inna rozmowa.
MAX_CALLBACK_DAYS = 60
NOTE_SNIPPET = 240


class FollowupProcessRow(BaseModel):
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    column: Literal["cv_sent", "client_interview"]
    stage_name: Optional[str] = None
    sent_at: datetime
    silent_since: datetime
    silent_days: int
    owner_id: Optional[int] = None
    owner_name: Optional[str] = None
    last_note: Optional[str] = None
    last_note_by: Optional[str] = None
    last_note_at: Optional[datetime] = None


class FollowupRow(BaseModel):
    candidate_id: int
    candidate_name: str
    phone: Optional[str] = None
    due_on: date
    state: Literal["overdue", "today", "tomorrow", "scheduled"]
    overdue_days: int = 0
    caller_id: Optional[int] = None
    caller_name: Optional[str] = None
    caller_reason: str
    processes: list[FollowupProcessRow]
    last_contact_at: Optional[datetime] = None
    last_contact_by: Optional[str] = None
    last_contact_kind: Optional[str] = None
    no_answer_count: int = 0
    pending: Optional[Literal["no_answer", "callback"]] = None


class FollowupHistoryRow(BaseModel):
    outcome: str
    user_name: Optional[str] = None
    created_at: datetime
    callback_on: Optional[date] = None
    note: Optional[str] = None
    call_id: Optional[int] = None
    has_transcript: bool = False
    has_recording: bool = False


class FollowupMeetingOut(BaseModel):
    id: int
    start: datetime
    end: Optional[datetime]
    join_url: Optional[str]
    recording_url: Optional[str]
    transcription_setup: str
    transcript_status: str


class FollowupDetail(BaseModel):
    candidate_id: int
    followup: Optional[FollowupRow] = None
    history: list[FollowupHistoryRow] = []
    meetings: list[FollowupMeetingOut] = []


class FollowupMeetingCreate(BaseModel):
    start: datetime
    end: datetime
    client_request_id: str = Field(min_length=16, max_length=80)

    @model_validator(mode="after")
    def _valid_window(self) -> "FollowupMeetingCreate":
        if self.start.tzinfo is None or self.end.tzinfo is None:
            raise ValueError("Podaj termin ze strefą czasową.")
        if self.start <= datetime.now(timezone.utc) or self.end <= self.start:
            raise ValueError(
                "Spotkanie musi mieć przyszły początek i późniejszy koniec."
            )
        if self.end - self.start > timedelta(hours=2):
            raise ValueError("Spotkanie follow-up może trwać najwyżej 2 godziny.")
        return self


class FollowupTranscriptOut(BaseModel):
    meeting_id: int
    text: str
    fetched_at: datetime


class FollowupOutcomeIn(BaseModel):
    outcome: Literal["connected", "changed", "no_answer", "callback"]
    note: Optional[str] = Field(default=None, max_length=4000)
    callback_on: Optional[date] = None
    # Id z POST /api/cloudtalk/initiate-call, nigdy dopasowanie po numerze.
    call_id: Optional[int] = Field(default=None, ge=1)
    # `changed`: co z każdym procesem — klucz to id rekrutacji.
    processes: dict[int, Literal["interested", "withdrawing"]] = {}

    @model_validator(mode="after")
    def _callback_needs_date(self) -> "FollowupOutcomeIn":
        if self.outcome == "callback" and self.callback_on is None:
            raise ValueError("Wybierz dzień, w którym oddzwonić.")
        if self.outcome != "callback":
            self.callback_on = None
        if self.outcome == "changed" and not (self.note or "").strip():
            raise ValueError("Opisz, co się zmieniło — trafi do właścicieli procesów.")
        return self


def _snippet(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= NOTE_SNIPPET else text[: NOTE_SNIPPET - 1] + "…"


async def serialize_rows(
    db: AsyncSession,
    followups: list[svc.Followup],
    *,
    today: date,
    with_notes: bool = False,
) -> list[FollowupRow]:
    """Wiersze API — ta sama postać dla pulpitu, Tablicy i profilu."""

    if not followups:
        return []
    user_ids: set[Optional[int]] = set()
    for f in followups:
        user_ids.add(f.caller_id)
        user_ids.update(p.owner_id for p in f.processes)
        if f.last_contact is not None:
            user_ids.add(f.last_contact.by)
    names = await svc.user_names(db, user_ids)
    last_notes: dict[tuple[int, int], tuple[str, Optional[int], datetime]] = {}
    if with_notes:
        pairs = [(f.candidate_id, p.job_id) for f in followups for p in f.processes]
        cand_ids = sorted({c for c, _ in pairs})
        job_ids = sorted({j for _, j in pairs})
        rows = (
            await db.execute(
                select(
                    Note.candidate_id,
                    Note.job_id,
                    Note.content,
                    Note.author_id,
                    Note.created_at,
                )
                .where(Note.candidate_id.in_(cand_ids), Note.job_id.in_(job_ids))
                .distinct(Note.candidate_id, Note.job_id)
                .order_by(
                    Note.candidate_id,
                    Note.job_id,
                    Note.created_at.desc(),
                    Note.id.desc(),
                )
            )
        ).all()
        extra = {author for *_, author, _ in rows if author and author not in names}
        names.update(await svc.user_names(db, extra))
        for cid, jid, content, author, at in rows:
            last_notes[(cid, jid)] = (content, author, at)

    out: list[FollowupRow] = []
    for f in followups:
        processes = []
        for p in f.processes:
            note = last_notes.get((f.candidate_id, p.job_id))
            processes.append(
                FollowupProcessRow(
                    job_id=p.job_id,
                    job_title=p.job_title,
                    client_name=p.client_name,
                    column=p.column,
                    stage_name=p.stage_name,
                    sent_at=p.sent_at,
                    silent_since=p.silent_since,
                    silent_days=max((today - svc.local_date(p.silent_since)).days, 0),
                    owner_id=p.owner_id,
                    owner_name=names.get(p.owner_id) if p.owner_id else None,
                    last_note=_snippet(note[0]) if note else None,
                    last_note_by=names.get(note[1]) if note and note[1] else None,
                    last_note_at=note[2] if note else None,
                )
            )
        contact = f.last_contact
        out.append(
            FollowupRow(
                candidate_id=f.candidate_id,
                candidate_name=f.candidate_name or f"Kandydat #{f.candidate_id}",
                phone=f.phone,
                due_on=f.due_on,
                state=f.state(today),
                overdue_days=f.overdue_days(today),
                caller_id=f.caller_id,
                caller_name=names.get(f.caller_id) if f.caller_id else None,
                caller_reason=f.caller_reason,
                processes=processes,
                last_contact_at=contact.at if contact else None,
                last_contact_by=names.get(contact.by)
                if contact and contact.by
                else None,
                last_contact_kind=contact.kind if contact else None,
                no_answer_count=f.no_answer_count,
                pending=f.pending,
            )
        )
    return out


async def _history(
    db: AsyncSession, candidate_id: int, limit: int = 5
) -> list[FollowupHistoryRow]:
    rows = (
        await db.execute(
            select(CandidateFollowup, Note.content)
            .outerjoin(Note, Note.id == CandidateFollowup.note_id)
            .where(
                CandidateFollowup.candidate_id == candidate_id,
                CandidateFollowup.outcome != "claim",
            )
            .order_by(CandidateFollowup.created_at.desc(), CandidateFollowup.id.desc())
            .limit(limit)
        )
    ).all()
    names = await svc.user_names(db, (r.user_id for r, _ in rows))
    call_ids = {
        int(r.details["call_id"])
        for r, _ in rows
        if isinstance(r.details, dict) and isinstance(r.details.get("call_id"), int)
    }
    calls = (
        {
            call.id: call
            for call in (
                await db.scalars(select(Call).where(Call.id.in_(call_ids)))
            ).all()
        }
        if call_ids
        else {}
    )
    history = []
    for r, content in rows:
        call = (
            calls.get(r.details.get("call_id")) if isinstance(r.details, dict) else None
        )
        if call is not None and call.candidate_id != candidate_id:
            call = None
        history.append(
            FollowupHistoryRow(
                outcome=r.outcome,
                user_name=names.get(r.user_id) if r.user_id else None,
                created_at=r.created_at,
                callback_on=r.callback_on,
                note=_snippet(content),
                call_id=call.id if call else None,
                has_transcript=bool(call.transcript) if call else False,
                has_recording=bool(call.recording_url) if call else False,
            )
        )
    return history


async def _detail(db: AsyncSession, candidate_id: int) -> FollowupDetail:
    now = datetime.now(timezone.utc)
    followups = await svc.load_followups(db, now=now, candidate_ids=[candidate_id])
    followup = followups.get(candidate_id)
    rows = (
        await serialize_rows(db, [followup], today=svc.local_date(now), with_notes=True)
        if followup
        else []
    )
    meeting_rows = (
        await db.execute(
            select(FollowupMeeting, CalendarEvent)
            .join(CalendarEvent, CalendarEvent.id == FollowupMeeting.calendar_event_id)
            .where(FollowupMeeting.candidate_id == candidate_id)
            .order_by(FollowupMeeting.created_at.desc())
            .limit(10)
        )
    ).all()
    return FollowupDetail(
        candidate_id=candidate_id,
        followup=rows[0] if rows else None,
        history=await _history(db, candidate_id),
        meetings=[
            FollowupMeetingOut(
                id=m.id,
                start=e.start_time,
                end=e.end_time,
                join_url=e.online_meeting_url,
                recording_url=e.recording_url,
                transcription_setup=m.transcription_setup,
                transcript_status=m.transcript_status,
            )
            for m, e in meeting_rows
        ],
    )


async def _require_candidate(db: AsyncSession, candidate_id: int) -> Candidate:
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiego kandydata.")
    return candidate


async def _require_waiting(db: AsyncSession, candidate_id: int) -> svc.Followup:
    followup = (await svc.load_followups(db, candidate_ids=[candidate_id])).get(
        candidate_id
    )
    if followup is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "FOLLOWUP_NOT_WAITING",
                "message": "Ten kandydat nie czeka już na odpowiedź klienta.",
            },
        )
    return followup


@router.get("/candidates/{candidate_id}", response_model=FollowupDetail)
async def get_candidate_followup(
    candidate_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> FollowupDetail:
    del current_user
    await _require_candidate(db, candidate_id)
    return await _detail(db, candidate_id)


@router.post("/candidates/{candidate_id}/teams-meetings", response_model=FollowupDetail)
async def schedule_teams_followup(
    candidate_id: int,
    body: FollowupMeetingCreate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> FollowupDetail:
    candidate = await _require_candidate(db, candidate_id)
    await _require_waiting(db, candidate_id)
    await followup_meetings.create_followup_meeting(
        db,
        candidate=candidate,
        organizer=current_user,
        start=body.start,
        end=body.end,
        client_request_id=body.client_request_id,
    )
    await db.commit()
    return await _detail(db, candidate_id)


@router.get(
    "/candidates/{candidate_id}/teams-meetings/{meeting_id}/transcript",
    response_model=FollowupTranscriptOut,
)
async def get_teams_followup_transcript(
    candidate_id: int,
    meeting_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> FollowupTranscriptOut:
    del current_user
    await _require_candidate(db, candidate_id)
    meeting = await db.get(FollowupMeeting, meeting_id)
    if (
        meeting is None
        or meeting.candidate_id != candidate_id
        or not meeting.transcript_text
    ):
        raise HTTPException(
            status_code=404, detail="Transkrypt nie jest jeszcze dostępny."
        )
    return FollowupTranscriptOut(
        meeting_id=meeting.id,
        text=meeting.transcript_text,
        fetched_at=meeting.transcript_fetched_at,
    )


def _process_label(p: svc.WaitingProcess) -> str:
    return " — ".join(x for x in (p.client_name, p.job_title) if x)


def _note_content(body: FollowupOutcomeIn, followup: svc.Followup) -> str:
    lead = (
        "Follow-up (klient milczy): coś się zmieniło."
        if body.outcome == "changed"
        else "Follow-up (klient milczy): kandydat dalej czeka na odpowiedź."
    )
    lines = [lead]
    if body.note and body.note.strip():
        lines.append(body.note.strip())
    labels = {"interested": "dalej zainteresowany", "withdrawing": "rezygnuje"}
    procs = []
    for p in followup.processes:
        flag = body.processes.get(p.job_id)
        procs.append(
            f"{_process_label(p)} ({labels[flag]})" if flag else _process_label(p)
        )
    lines.append("Procesy: " + "; ".join(procs))
    return "\n".join(lines)


async def _signal_owners(
    db: AsyncSession,
    *,
    followup: svc.Followup,
    body: FollowupOutcomeIn,
    author: User,
) -> int:
    """Dzwonek do właścicieli procesów, których dotyczy zmiana.

    Jeden wpis na właściciela, z WSZYSTKIMI jego procesami, których dotyczy
    zmiana. Drugi sygnał tego samego dnia o tym samym kandydacie nie ginie na
    dobowym dedupie (`ix_notif_dedup_daily`, audyt 24.09.2026): dopisujemy go
    do dzisiejszego wpisu i oznaczamy jako nieprzeczytany.
    """

    from app.services.workforce_availability import workforce_context  # noqa: PLC0415

    # Runda 8 (R8-N7-1): właściciel na zastępstwie z COMPASS — sygnał idzie
    # do osoby, która za niego pracuje (jak telefon w `compute_followup`).
    workforce = await workforce_context(db)
    flagged = {jid for jid, flag in body.processes.items() if flag == "withdrawing"}
    by_owner: dict[int, list[svc.WaitingProcess]] = {}
    for p in followup.processes:
        if p.owner_id is None or (flagged and p.job_id not in flagged):
            continue
        recipient = workforce.performer(p.owner_id)
        if recipient is None or recipient == author.id:
            continue
        by_owner.setdefault(recipient, []).append(p)

    sent = 0
    author_name = author.name or author.email
    for owner_id, processes in by_owner.items():
        withdrawing = any(p.job_id in flagged for p in processes)
        title = (
            f"{followup.candidate_name} rezygnuje z procesu"
            if withdrawing
            else f"Follow-up: zmiana u {followup.candidate_name}"
        )
        labels = "; ".join(_process_label(p) for p in processes)
        message = f"{labels}. {author_name}: {_snippet(body.note) or ''}".strip()
        created = await emit(
            db,
            user_id=owner_id,
            title=title,
            message=message,
            ntype=NotificationType.candidate_followup_signal,
            related_entity_type="candidate",
            related_entity_id=followup.candidate_id,
            link=f"/jobs/{processes[0].job_id}?candidate={followup.candidate_id}",
        )
        if created is not None:
            sent += 1
            continue
        if await _append_to_todays_signal(
            db,
            user_id=owner_id,
            candidate_id=followup.candidate_id,
            title=title if withdrawing else None,
            message=message,
        ):
            sent += 1
    return sent


async def _append_to_todays_signal(
    db: AsyncSession,
    *,
    user_id: int,
    candidate_id: int,
    title: Optional[str],
    message: str,
) -> bool:
    """Dopisz sygnał do dzisiejszego wpisu (ten sam dobowy klucz co dedup).

    Brak wpisu = `emit` odmówił przez bramkę odbiorcy (nieaktywne konto, brak
    sekcji) — wtedy nic nie dopisujemy.
    """
    from sqlalchemy import func  # noqa: PLC0415

    from app.core.config import settings  # noqa: PLC0415
    from app.core.scheduling import business_today  # noqa: PLC0415
    from app.models.notification import Notification  # noqa: PLC0415

    existing = await db.scalar(
        select(Notification)
        .where(
            Notification.user_id == user_id,
            Notification.notification_type
            == NotificationType.candidate_followup_signal,
            Notification.related_entity_type == "candidate",
            Notification.related_entity_id == candidate_id,
            func.date(func.timezone(settings.BUSINESS_TZ, Notification.created_at))
            == business_today(settings.BUSINESS_TZ),
        )
        .order_by(Notification.created_at.desc())
        .limit(1)
        .with_for_update()
    )
    if existing is None:
        return False
    if message not in (existing.message or ""):
        existing.message = f"{existing.message}\n{message}".strip()[:4000]
    if title:
        existing.title = title[:255]
    existing.is_read = False
    return True


@router.post("/candidates/{candidate_id}/outcome", response_model=FollowupDetail)
async def record_followup_outcome(
    candidate_id: int,
    body: FollowupOutcomeIn,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> FollowupDetail:
    candidate = await _require_candidate(db, candidate_id)
    followup = await _require_waiting(db, candidate_id)
    today = svc.today_local()
    if body.callback_on is not None and not (
        today <= body.callback_on <= today + timedelta(days=MAX_CALLBACK_DAYS)
    ):
        raise HTTPException(
            status_code=422,
            detail=f"Dzień oddzwonienia musi przypadać w ciągu {MAX_CALLBACK_DAYS} dni.",
        )
    job_ids = {p.job_id for p in followup.processes}
    unknown = set(body.processes) - job_ids
    if unknown:
        raise HTTPException(
            status_code=422,
            detail="Wybrany proces nie czeka już na odpowiedź klienta — odśwież okno.",
        )

    if body.call_id is not None:
        call = await db.get(Call, body.call_id, with_for_update=True)
        if (
            call is None
            or call.candidate_id != candidate_id
            or call.user_id != current_user.id
            or call.direction != CallDirection.outbound
            or not call.cloudtalk_call_id
        ):
            raise HTTPException(
                status_code=422,
                detail="Rozmowa CloudTalk nie należy do tego kandydata i użytkownika.",
            )
        previous = await db.scalar(
            select(CandidateFollowup.id).where(
                CandidateFollowup.details.contains({"call_id": body.call_id})
            )
        )
        if previous is not None:
            raise HTTPException(
                status_code=409,
                detail="Ta rozmowa jest już przypisana do innego follow-upu.",
            )

    entry = CandidateFollowup(
        candidate_id=candidate_id,
        user_id=current_user.id,
        outcome=body.outcome,
        callback_on=body.callback_on,
        details={
            "processes": {str(k): v for k, v in body.processes.items()},
            "job_ids": sorted(job_ids),
            **({"call_id": body.call_id} if body.call_id is not None else {}),
        },
    )
    db.add(entry)
    await db.flush()

    if body.outcome in ("connected", "changed"):
        note = Note(
            content=_note_content(body, followup),
            note_type=NoteType.call,
            candidate_id=candidate_id,
            author_id=current_user.id,
            source_ref=f"followup:{entry.id}",
        )
        db.add(note)
        await db.flush()
        entry.note_id = note.id
        candidate.notes_count = (candidate.notes_count or 0) + 1
        db.add(
            UserActivity(
                user_id=current_user.id,
                action_type=UserActionType.note_added,
                entity_type="candidate",
                entity_id=candidate_id,
                details={
                    "note_id": note.id,
                    "note_type": NoteType.call.value,
                    "mentioned_count": 0,
                    "source": "candidate_followup",
                },
            )
        )
    if body.outcome == "changed":
        await _signal_owners(db, followup=followup, body=body, author=current_user)
    await db.commit()
    return await _detail(db, candidate_id)


@router.post("/candidates/{candidate_id}/claim", response_model=FollowupDetail)
async def claim_followup(
    candidate_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> FollowupDetail:
    await _require_candidate(db, candidate_id)
    await _require_waiting(db, candidate_id)
    db.add(
        CandidateFollowup(
            candidate_id=candidate_id, user_id=current_user.id, outcome="claim"
        )
    )
    await db.commit()
    return await _detail(db, candidate_id)
