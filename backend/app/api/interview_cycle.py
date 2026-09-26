"""„Rozmowy u klienta” — API cyklu rozmowy kandydata u klienta (0338).

Trasy:

* ``GET  /api/interview-cycle`` — agenda, lista „Do zrobienia” i kroki par
  w zakresie wołającego (``scope=mine|jobs|all``).
* ``POST /api/interview-cycle/slots`` — DL wpisuje terminy od klienta.
* ``POST /api/interview-cycle/slots/{id}/choose`` — rekruter wybiera termin
  ustalony z kandydatem.
* ``POST /api/interview-cycle/slots/{id}/confirm`` — DL potwierdza termin
  u klienta → wydarzenie ``client_interview``.
* ``POST /api/interview-cycle/slots/{id}/cancel``
* ``PUT  /api/interview-cycle/events/{event_id}/debrief`` — debrief po
  telefonie do kandydata (jak poszło, pytania klienta, czy przyjmie ofertę).
* ``GET  /api/interview-cycle/client-questions`` — pytania, które klient
  zadawał poprzednim kandydatom (z debriefów).

Uprawnienia nie są nowe: sekcja Pipeline, role zapisu kalendarza i
członkostwo w rekrutacji (``ensure_job_membership``) jak przy każdym
wydarzeniu związanym z rekrutacją.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_core import PydanticCustomError
from sqlalchemy import exists, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calendar_access import user_can_view_event
from app.api.candidate_access import user_has_candidate_read
from app.api.recruitment_access import (
    CalendarWriteAccess,
    RecruitmentAssessmentWriteAccess,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_job_read_access,
    job_read_scope_clause,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.calendar_event import CalendarEvent, EventType
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionSource,
    JobQuestion,
    JobQuestionAddedBySource,
)
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.recruitment_pipeline import PipelineStage
from app.models.user import User, UserRole
from app.services import interview_slots
from app.services.interview_cycle import load_overview
from app.services.debrief_gate import interview_not_started_message
from app.services.pipeline_auto_move import auto_advance, run_after_commit
from app.services.pipeline_realtime import broadcast_pipeline_changed
from app.services.workforce_availability import operational_owner_ids

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

# Terminy od klienta wpisuje osoba prowadząca klienta: DL, TAC albo nadzór.
_SLOT_OWNER_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
)
_OVERSIGHT_ROLES = (UserRole.admin, UserRole.head_of_recruitment)

MAX_DEBRIEF_QUESTIONS = 20
_WHITESPACE_RE = re.compile(r"\s+")


# ── Schematy ─────────────────────────────────────────────────────────────────


class CycleStep(BaseModel):
    key: str
    label: str
    state: str
    at: Optional[datetime] = None
    event_id: Optional[int] = None
    meta: Optional[str] = None
    # 0370: jakość odbytego prepu — good | ok | weak | unrecorded | pending.
    quality: Optional[str] = None


class SlotItem(BaseModel):
    start: datetime
    end: Optional[datetime] = None


class SlotRequestOut(BaseModel):
    id: int
    status: str
    slots: list[SlotItem]
    chosen_index: Optional[int] = None
    respond_by: Optional[datetime] = None
    recruiter_id: Optional[int] = None
    created_by: Optional[int] = None
    duration_minutes: int
    note: Optional[str] = None
    event_id: Optional[int] = None
    # Pipeline v4: terminy od klienta przesunęły kartę na „Rozmowa u klienta”
    # (tylko w odpowiedzi na utworzenie wniosku).
    moved_to_client_interview: bool = False


class DebriefSummary(BaseModel):
    id: int
    overall_impression: Optional[int] = None
    offer_acceptance: Optional[str] = None
    acceptance_condition: Optional[str] = None


class PairInfo(BaseModel):
    candidate_id: int
    candidate_name: Optional[str] = None
    candidate_email: Optional[str] = None
    job_id: int
    job_title: Optional[str] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None


class CycleItem(PairInfo):
    steps: list[CycleStep]
    current_step: Optional[str] = None
    latest_stage: Optional[str] = None
    slot_request: Optional[SlotRequestOut] = None
    interview_event_id: Optional[int] = None
    debrief: Optional[DebriefSummary] = None


class AgendaEntry(PairInfo):
    kind: Literal["prep", "prep2", "interview", "call", "tentative"]
    start: datetime
    end: Optional[datetime] = None
    event_id: Optional[int] = None
    slot_request_id: Optional[int] = None
    online_meeting_url: Optional[str] = None
    done: bool = False
    # 0370: prep założony z NEXUSA (Teams) i jego ocena po spotkaniu.
    from_nexus: bool = False
    prep_quality: Optional[str] = None
    prep_meta: Optional[str] = None


class TodoEntry(PairInfo):
    kind: str
    priority: int
    due: Optional[datetime] = None
    event_id: Optional[int] = None
    slot_request_id: Optional[int] = None
    # 0370: brak prepu na dobę przed rozmową u klienta.
    urgent: bool = False


class CycleOverview(BaseModel):
    generated_at: datetime
    scope: str
    call_window_minutes: int
    items: list[CycleItem]
    agenda: list[AgendaEntry]
    todos: list[TodoEntry]
    truncated: bool = False


class SlotRequestCreate(BaseModel):
    candidate_id: int
    job_id: int
    slots: list[SlotItem] = Field(
        ..., min_length=1, max_length=interview_slots.MAX_SLOTS
    )
    duration_minutes: int = Field(60, ge=15, le=480)
    respond_by: Optional[datetime] = None
    note: Optional[str] = Field(None, max_length=1000)
    recruiter_id: Optional[int] = None


class SlotChoose(BaseModel):
    index: int = Field(..., ge=0)


class SlotConfirm(BaseModel):
    index: Optional[int] = Field(None, ge=0)
    add_to_outlook: bool = True
    # Rozmowa, którą ten termin przekłada (jawny wybór DL; bez niego nic nie
    # jest odwoływane — para może mieć kilka rund naraz).
    supersedes_event_id: Optional[int] = None


class SlotConfirmOut(BaseModel):
    request: SlotRequestOut
    event_id: int
    outlook: str
    cancelled_event_id: Optional[int] = None


class ReplaceableInterviewOut(BaseModel):
    id: int
    start_time: datetime
    end_time: Optional[datetime] = None


DebriefOutcome = Literal["good", "medium", "bad"]
OfferAcceptance = Literal["yes", "likely", "no", "unknown"]
_OUTCOME_TO_IMPRESSION = {"good": 5, "medium": 3, "bad": 1}


class DebriefIn(BaseModel):
    outcome: DebriefOutcome
    candidate_comment: Optional[str] = Field(None, max_length=4000)
    questions: list[str] = Field(default_factory=list)
    offer_acceptance: OfferAcceptance
    acceptance_condition: Optional[str] = Field(None, max_length=2000)
    notify_dl: bool = True
    # Jawne „klient nie zadawał pytań” — pusta lista bez tej flagi to brak
    # informacji, nie odpowiedź (bramka przed „Umową”, ``services/debrief_gate``).
    no_client_questions: bool = False

    @field_validator("questions")
    @classmethod
    def _clean_questions(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value:
            text = _WHITESPACE_RE.sub(" ", (raw or "").strip())
            if not text:
                continue
            if len(text) > 500:
                raise ValueError("Pytanie może mieć najwyżej 500 znaków.")
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
        if len(cleaned) > MAX_DEBRIEF_QUESTIONS:
            raise ValueError(f"Najwyżej {MAX_DEBRIEF_QUESTIONS} pytań w debriefie.")
        return cleaned

    @model_validator(mode="after")
    def _questions_or_confirmation(self) -> "DebriefIn":
        if self.questions:
            # Pytania są, więc „nie pytał” byłoby sprzeczne — pytania wygrywają.
            self.no_client_questions = False
        elif not self.no_client_questions:
            # PydanticCustomError: 422 bez prefiksu „Value error, ...”.
            raise PydanticCustomError(
                "debrief_questions_required",
                "Wpisz pytania klienta albo zaznacz, że klient ich nie zadawał.",
            )
        return self


class DebriefOut(BaseModel):
    id: int
    calendar_event_id: int
    candidate_id: int
    job_id: Optional[int] = None
    outcome: Optional[DebriefOutcome] = None
    candidate_comment: Optional[str] = None
    questions: list[str] = []
    offer_acceptance: Optional[str] = None
    acceptance_condition: Optional[str] = None
    no_client_questions: bool = False
    questions_saved: int = 0


class InterviewEventOut(BaseModel):
    """Termin rozmowy u klienta — okno debriefu pyta, czy już się zaczęła."""

    id: int
    candidate_id: int
    job_id: Optional[int] = None
    start: datetime
    end: Optional[datetime] = None
    # Debrief da się zapisać dopiero od rozpoczęcia rozmowy (``PUT …/debrief``).
    started: bool


class ClientQuestionOut(BaseModel):
    id: int
    text: str
    created_at: Optional[datetime] = None


class ArchiveQuestionOut(BaseModel):
    id: int
    text: str
    # Technologie tej rekrutacji, o które pyta pytanie — dlaczego je widać.
    matched: list[str]


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _slot_out(req: ClientInterviewSlotRequest) -> SlotRequestOut:
    return SlotRequestOut(
        id=req.id,
        status=req.status,
        slots=[SlotItem(**s) for s in (req.slots or [])],
        chosen_index=req.chosen_index,
        respond_by=req.respond_by,
        recruiter_id=req.recruiter_id,
        created_by=req.created_by,
        duration_minutes=req.duration_minutes,
        note=req.note,
        event_id=req.event_id,
    )


def _is_owner(user: User, user_id: Optional[int]) -> bool:
    return user_id is not None and user_id in operational_owner_ids(user)


async def _ensure_slot_recruiter(db: AsyncSession, user_id: int, job_id: int) -> None:
    """Wskazany rekruter wniosku: aktywne konto roli wewnętrznej z dostępem
    do rekrutacji — inaczej 422 po polsku.

    Bez tego nieistniejące id kończyło się naruszeniem klucza obcego, które
    handler brał za „otwarte terminy" (409), a dowolne konto (także spoza
    zespołu) dostawało wybór terminu i blokadę w swoim Outlooku (audyt
    25.09.2026).
    """

    detail = (
        "Wybierz aktywną osobę z zespołu rekrutacji, która wybierze termin "
        "z kandydatem."
    )
    if not await interview_slots.slot_recruiter_eligible(db, user_id, job_id):
        raise HTTPException(status_code=422, detail=detail)


async def _can_see_interview(
    db: AsyncSession, event: CalendarEvent, user: User
) -> bool:
    """Właściciel, uczestnik albo rola z odczytem kalendarza — oraz każdy
    z dostępem do rekrutacji wydarzenia.

    Rekrutacje i kandydatów widzą wszyscy (decyzja Artura 23.09.2026), więc
    Delivery Lead rekrutacji, który nie jest właścicielem rozmowy, musi móc
    zapisać debrief — inaczej dostawał 404, a bramka debriefu przed „Umową”
    (409 `DEBRIEF_REQUIRED`) zatrzymywała go bez wyjścia (audyt 25.09.2026).
    """

    if user_can_view_event(event, user):
        return True
    if event.job_id is None:
        return False
    try:
        await ensure_job_read_access(db, user, event.job_id)
    except HTTPException:
        return False
    return True


async def _ensure_slot_owner(
    db: AsyncSession, user: User, req: ClientInterviewSlotRequest
) -> None:
    """Potwierdzić termin u klienta może autor wniosku albo DL/TAC rekrutacji."""
    if _is_owner(user, req.created_by):
        return
    if not user.has_any_role(*_SLOT_OWNER_ROLES):
        raise HTTPException(
            status_code=403,
            detail="Termin u klienta potwierdza Delivery Lead albo TAC rekrutacji.",
        )
    await ensure_job_membership(db, user, req.job_id)


async def _ensure_recruiter(
    db: AsyncSession, user: User, req: ClientInterviewSlotRequest
) -> None:
    """Wybrać termin może rekruter kandydata albo członek zespołu rekrutacji."""
    if _is_owner(user, req.recruiter_id):
        return
    await ensure_job_membership(db, user, req.job_id)


def _question_hash(text: str) -> str:
    norm = _WHITESPACE_RE.sub(" ", text.strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


def _outcome_from_impression(value: Optional[int]) -> Optional[DebriefOutcome]:
    if value is None:
        return None
    if value >= 4:
        return "good"
    if value == 3:
        return "medium"
    return "bad"


def _questions_from_text(value: Optional[str]) -> list[str]:
    return [line.strip() for line in (value or "").splitlines() if line.strip()]


def _debrief_out(fb: InterviewFeedback, *, questions_saved: int = 0) -> DebriefOut:
    return DebriefOut(
        id=fb.id,
        calendar_event_id=fb.calendar_event_id,
        candidate_id=fb.candidate_id,
        job_id=fb.job_id,
        outcome=_outcome_from_impression(fb.overall_impression),
        candidate_comment=fb.concerns,
        questions=_questions_from_text(fb.client_questions),
        offer_acceptance=fb.offer_acceptance,
        acceptance_condition=fb.acceptance_condition,
        no_client_questions=bool(fb.no_client_questions),
        questions_saved=questions_saved,
    )


async def _save_client_questions(
    db: AsyncSession,
    *,
    questions: list[str],
    client_id: Optional[int],
    job_id: Optional[int],
    user_id: int,
) -> int:
    """Pytania klienta → bank pytań klienta + pin do rekrutacji.

    Dedup po znormalizowanym tekście w obrębie klienta (unikat
    ``uq_iq_client_hash``). Bez klienta nie zapisujemy — pytanie bez klienta
    trafiłoby do GLOBALNEGO banku i wyciekło do prepów innych klientów.
    """
    if not questions or client_id is None:
        return 0
    saved = 0
    for text in questions:
        norm_hash = _question_hash(text)
        question = await db.scalar(
            select(InterviewQuestion).where(
                InterviewQuestion.client_id == client_id,
                InterviewQuestion.normalized_text_hash == norm_hash,
            )
        )
        if question is None:
            question = InterviewQuestion(
                text=text,
                client_id=client_id,
                source=InterviewQuestionSource.client_debrief,
                normalized_text_hash=norm_hash,
                skill_tags=[],
                created_by=user_id,
            )
            try:
                async with db.begin_nested():
                    db.add(question)
                    await db.flush()
            except IntegrityError:
                question = await db.scalar(
                    select(InterviewQuestion).where(
                        InterviewQuestion.client_id == client_id,
                        InterviewQuestion.normalized_text_hash == norm_hash,
                    )
                )
                if question is None:
                    continue
            saved += 1
        elif question.source == InterviewQuestionSource.legacy_import:
            # Klient zadał znowu pytanie z archiwum rozmów (0383) — od teraz to
            # zwykły debrief i trafia do list „co klient pytał ostatnio”.
            question.source = InterviewQuestionSource.client_debrief
            saved += 1
        if job_id is not None:
            pinned = await db.scalar(
                select(JobQuestion.id).where(
                    JobQuestion.job_id == job_id,
                    JobQuestion.question_id == question.id,
                )
            )
            if pinned is None:
                try:
                    async with db.begin_nested():
                        db.add(
                            JobQuestion(
                                job_id=job_id,
                                question_id=question.id,
                                is_pinned=True,
                                added_by_source=JobQuestionAddedBySource.manual,
                                added_by_user_id=user_id,
                                order_index=10_000.0 + saved,
                            )
                        )
                        await db.flush()
                except IntegrityError:
                    pass
    return saved


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.get("/interview-cycle", response_model=CycleOverview)
async def get_cycle_overview(
    current_user: RecruitmentReadAccess,
    scope: Literal["mine", "jobs", "all"] = Query("mine"),
    days_back: int = Query(14, ge=1, le=60),
    days_ahead: int = Query(30, ge=1, le=90),
    db: AsyncSession = Depends(get_db),
) -> CycleOverview:
    if scope == "all" and not current_user.has_any_role(*_OVERSIGHT_ROLES):
        raise HTTPException(
            status_code=403,
            detail="Widok całego zespołu jest dostępny dla administratora i HoR.",
        )
    data = await load_overview(
        db,
        current_user,
        scope=scope,
        days_back=days_back,
        days_ahead=days_ahead,
        can_read_candidates=user_has_candidate_read(current_user),
    )
    return CycleOverview(**data)


@router.post(
    "/interview-cycle/slots",
    response_model=SlotRequestOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_slot_request(
    body: SlotRequestCreate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> SlotRequestOut:
    if not current_user.has_any_role(*_SLOT_OWNER_ROLES):
        raise HTTPException(
            status_code=403,
            detail="Terminy od klienta dodaje Delivery Lead albo TAC rekrutacji.",
        )
    await ensure_job_membership(db, current_user, body.job_id)
    job = await db.get(Job, body.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    if not await interview_slots.pair_in_pipeline(
        db, candidate_id=body.candidate_id, job_id=body.job_id
    ):
        raise HTTPException(
            status_code=422,
            detail="Kandydat nie jest w pipeline tej rekrutacji.",
        )
    now = datetime.now(timezone.utc)
    slots = interview_slots.normalize_slots(
        [s.model_dump() for s in body.slots],
        duration_minutes=body.duration_minutes,
        now=now,
    )
    if body.recruiter_id is not None:
        await _ensure_slot_recruiter(db, body.recruiter_id, body.job_id)
    recruiter_id = body.recruiter_id or await interview_slots.default_recruiter_id(
        db, candidate_id=body.candidate_id, job_id=body.job_id
    )
    req = ClientInterviewSlotRequest(
        candidate_id=body.candidate_id,
        job_id=body.job_id,
        client_id=job.client_id,
        created_by=current_user.id,
        recruiter_id=recruiter_id,
        slots=slots,
        duration_minutes=body.duration_minutes,
        respond_by=body.respond_by,
        note=(body.note or "").strip() or None,
    )
    db.add(req)
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Ten kandydat ma już otwarte terminy do wyboru w tej rekrutacji — "
                "anuluj je albo dokończ wybór."
            ),
        ) from exc
    # Pipeline v4 (23.09.2026): terminy od klienta = kandydat JEST w rozmowie
    # u klienta. Karta jedzie tam sama — wyłącznie do przodu; proces zamknięty
    # albo karta już dalej zostają bez zmian.
    # Ruch jest dodatkiem do wniosku: jego awaria (savepoint) zostawia kartę
    # na miejscu i nie cofa terminów, które DL właśnie wpisał.
    actor_id = current_user.id
    moved = None
    try:
        async with db.begin_nested():
            moved = await auto_advance(
                db,
                candidate_id=body.candidate_id,
                job_id=body.job_id,
                target=PipelineStage.client_interview,
                actor_user_id=actor_id,
                source="interview_slots",
                note="Auto: terminy od klienta",
            )
    except Exception:  # noqa: BLE001 — ruch karty nie może wywrócić wniosku
        moved = None
        logger.exception(
            "interview slots: auto move to client_interview failed "
            "(candidate %s, job %s)",
            body.candidate_id,
            body.job_id,
        )
    await interview_slots.notify(
        db,
        user_id=recruiter_id,
        ntype=NotificationType.interview_slots_requested,
        req=req,
        title="Terminy rozmowy od klienta",
        message=(
            f"{len(slots)} terminy rozmowy u klienta do ustalenia z kandydatem "
            f"({job.title})."
        ),
        actor_id=actor_id,
    )
    # 0371: terminy od klienta = klient się odezwał → „Klient milczy” wraca
    # do „Szukamy kandydatów”. Nigdy nie rzuca.
    from app.services.request_work_state import (  # noqa: PLC0415
        wake_on_client_response,
    )

    await wake_on_client_response(
        db, job_id=body.job_id, stage=None, reason="client_slots"
    )
    await db.commit()
    await db.refresh(req)
    out = _slot_out(req)
    if moved is not None:
        # Live kanban: reszta zespołu odświeża tablicę (best-effort).
        await broadcast_pipeline_changed(db, body.job_id, actor_id)
        # Runda 7 (N7-4): powiadomienia o etapie i profil ryzyka — jak po
        # `/move`. Po commicie, nigdy nie rzuca.
        await run_after_commit(db, stage_id=moved.id, mover=current_user)
    out.moved_to_client_interview = moved is not None
    return out


@router.post(
    "/interview-cycle/slots/{request_id}/choose", response_model=SlotRequestOut
)
async def choose_slot(
    request_id: int,
    body: SlotChoose,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> SlotRequestOut:
    req = await interview_slots.lock_request(db, request_id)
    await _ensure_recruiter(db, current_user, req)
    interview_slots.choose(req, body.index, user_id=current_user.id)
    await db.flush()
    for recipient in await interview_slots.slot_owner_recipients(db, req):
        await interview_slots.notify(
            db,
            user_id=recipient,
            ntype=NotificationType.interview_slot_chosen,
            req=req,
            title="Kandydat wybrał termin",
            message="Rekruter ustalił termin z kandydatem — potwierdź go u klienta.",
            actor_id=current_user.id,
        )
    await db.commit()
    await db.refresh(req)
    return _slot_out(req)


@router.post(
    "/interview-cycle/slots/{request_id}/confirm", response_model=SlotConfirmOut
)
async def confirm_slot(
    request_id: int,
    body: SlotConfirm,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> SlotConfirmOut:
    req = await interview_slots.lock_request(db, request_id)
    await _ensure_slot_owner(db, current_user, req)
    event, outlook = await interview_slots.confirm(
        db,
        req,
        user_id=current_user.id,
        index=body.index,
        add_to_outlook=body.add_to_outlook,
        supersedes_event_id=body.supersedes_event_id,
    )
    await interview_slots.notify(
        db,
        # Właściciel rozmowy, nie surowy rekruter wniosku — ten mógł odejść
        # przed potwierdzeniem (runda 6 audytu).
        user_id=event.operational_owner_id,
        ntype=NotificationType.interview_slot_confirmed,
        req=req,
        title="Rozmowa u klienta potwierdzona",
        message=(
            "Termin rozmowy jest potwierdzony u klienta i jest w Twoim kalendarzu. "
            "Zaplanuj prep z kandydatem."
        ),
        actor_id=current_user.id,
    )
    await db.commit()
    await db.refresh(req)
    return SlotConfirmOut(
        request=_slot_out(req),
        event_id=event.id,
        outlook=outlook,
        cancelled_event_id=body.supersedes_event_id,
    )


@router.get(
    "/interview-cycle/slots/{request_id}/replaceable",
    response_model=list[ReplaceableInterviewOut],
)
async def list_replaceable_interviews(
    request_id: int,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> list[ReplaceableInterviewOut]:
    """Nieodbyte rozmowy pary, które potwierdzany termin może przełożyć —
    okno potwierdzenia pyta DL, czy to przełożenie (runda 6 audytu)."""
    req = await db.get(ClientInterviewSlotRequest, request_id)
    if req is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono wniosku o terminy.")
    await _ensure_slot_owner(db, current_user, req)
    rows = await interview_slots.replaceable_interviews(db, req)
    return [
        ReplaceableInterviewOut(
            id=ev.id, start_time=ev.start_time, end_time=ev.end_time
        )
        for ev in rows
    ]


@router.post(
    "/interview-cycle/slots/{request_id}/cancel", response_model=SlotRequestOut
)
async def cancel_slot_request(
    request_id: int,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> SlotRequestOut:
    req = await interview_slots.lock_request(db, request_id)
    if not (
        _is_owner(current_user, req.created_by)
        or _is_owner(current_user, req.recruiter_id)
    ):
        await _ensure_slot_owner(db, current_user, req)
    interview_slots.cancel(req)
    await db.commit()
    await db.refresh(req)
    return _slot_out(req)


async def _load_interview_event(
    db: AsyncSession, event_id: int, user: User
) -> CalendarEvent:
    event = await db.get(CalendarEvent, event_id)
    if event is None or not await _can_see_interview(db, event, user):
        raise HTTPException(status_code=404, detail="Nie znaleziono rozmowy.")
    if event.event_type != EventType.client_interview or event.candidate_id is None:
        raise HTTPException(
            status_code=422,
            detail="Debrief zapisuje się pod rozmową kandydata u klienta.",
        )
    return event


def _event_start_utc(event: CalendarEvent) -> datetime:
    start = event.start_time
    return start if start.tzinfo is not None else start.replace(tzinfo=timezone.utc)


@router.get("/interview-cycle/events/{event_id}", response_model=InterviewEventOut)
async def get_interview_event(
    event_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> InterviewEventOut:
    """Termin rozmowy u klienta dla okna debriefu (także z bramki na tablicy,
    która zna tylko id wydarzenia)."""
    event = await _load_interview_event(db, event_id, current_user)
    if event.job_id is not None:
        await ensure_job_read_access(db, current_user, event.job_id)
    start = _event_start_utc(event)
    return InterviewEventOut(
        id=event.id,
        candidate_id=event.candidate_id,
        job_id=event.job_id,
        start=start,
        end=event.end_time,
        started=start <= datetime.now(timezone.utc),
    )


@router.get(
    "/interview-cycle/events/{event_id}/debrief", response_model=Optional[DebriefOut]
)
async def get_debrief(
    event_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> Optional[DebriefOut]:
    event = await _load_interview_event(db, event_id, current_user)
    if event.job_id is not None:
        await ensure_job_read_access(db, current_user, event.job_id)
    fb = await db.scalar(
        select(InterviewFeedback).where(
            InterviewFeedback.calendar_event_id == event.id,
            InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
        )
    )
    return _debrief_out(fb) if fb is not None else None


@router.put("/interview-cycle/events/{event_id}/debrief", response_model=DebriefOut)
async def save_debrief(
    event_id: int,
    body: DebriefIn,
    current_user: RecruitmentAssessmentWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> DebriefOut:
    """Upsert debriefu = feedback strony kandydata pod rozmową u klienta.

    Pytania trafiają do trzech miejsc: tekstu feedbacku (kompatybilność z
    kartą kandydata), banku pytań KLIENTA (prep następnych kandydatów) i pinu
    przy tej rekrutacji (prep kit bierze pinned jako pierwsze).
    """
    event = await _load_interview_event(db, event_id, current_user)
    if not _is_owner(current_user, event.operational_owner_id or event.created_by):
        if event.job_id is not None:
            await ensure_job_membership(db, current_user, event.job_id)
    start = _event_start_utc(event)
    if start > datetime.now(timezone.utc):
        # Debrief to zapis telefonu PO rozmowie — przed jej rozpoczęciem nie ma
        # czego raportować, a zapis zamykałby kroki „Telefon” i „Debrief” oraz
        # bramkę przed „Umową” (test na produkcji 23.09.2026).
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=interview_not_started_message(start),
        )
    fb = await db.scalar(
        select(InterviewFeedback)
        .where(
            InterviewFeedback.calendar_event_id == event.id,
            InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
        )
        .with_for_update()
    )
    if fb is None:
        fb = InterviewFeedback(
            calendar_event_id=event.id,
            candidate_id=event.candidate_id,
            job_id=event.job_id,
            author_id=current_user.id,
            feedback_source=FeedbackSource.candidate_side,
        )
        db.add(fb)
    fb.overall_impression = _OUTCOME_TO_IMPRESSION[body.outcome]
    fb.concerns = (body.candidate_comment or "").strip() or None
    fb.client_questions = "\n".join(body.questions) or None
    fb.no_client_questions = body.no_client_questions
    fb.offer_acceptance = body.offer_acceptance
    fb.acceptance_condition = (body.acceptance_condition or "").strip() or None
    try:
        await db.flush()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Ktoś właśnie zapisał debrief tej rozmowy — odśwież i spróbuj ponownie.",
        ) from exc
    if event.needs_attention:
        event.needs_attention = False

    client_id = event.client_id
    if client_id is None and event.job_id is not None:
        client_id = await db.scalar(select(Job.client_id).where(Job.id == event.job_id))
    saved = await _save_client_questions(
        db,
        questions=body.questions,
        client_id=client_id,
        job_id=event.job_id,
        user_id=current_user.id,
    )

    if body.notify_dl and event.job_id is not None:
        dl_id = await db.scalar(
            select(Job.delivery_lead_id).where(Job.id == event.job_id)
        )
        if dl_id and dl_id != current_user.id:
            from app.services.notification_triggers import emit

            label = {
                "yes": "przyjmie",
                "likely": "raczej przyjmie",
                "no": "nie przyjmie",
                "unknown": "nie wiadomo, czy przyjmie",
            }[body.offer_acceptance]
            outcome = {"good": "dobrze", "medium": "średnio", "bad": "źle"}[
                body.outcome
            ]
            try:
                async with db.begin_nested():
                    await emit(
                        db,
                        user_id=dl_id,
                        title="Debrief po rozmowie u klienta",
                        message=f"Rozmowa poszła {outcome}; kandydat {label} ofertę.",
                        ntype=NotificationType.interview_debrief_saved,
                        related_entity_type="calendar_event",
                        related_entity_id=event.id,
                        link=interview_slots.cycle_link(
                            event.candidate_id, event.job_id
                        ),
                    )
            except Exception:  # noqa: BLE001 — dzwonek nie cofa debriefu
                import logging

                logging.getLogger(__name__).exception(
                    "debrief notification failed for event %s", event.id
                )
    await db.commit()
    await db.refresh(fb)
    return _debrief_out(fb, questions_saved=saved)


@router.get("/interview-cycle/client-questions", response_model=list[ClientQuestionOut])
async def list_client_questions(
    current_user: RecruitmentReadAccess,
    job_id: Optional[int] = Query(None),
    client_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[ClientQuestionOut]:
    """Pytania, które klient zadawał kandydatom (z debriefów).

    Zwykle po rekrutacji (``job_id``): dostęp do rekrutacji jest tym, co
    sprawdzamy wszędzie indziej, a klient wynika z niej. ``client_id`` służy
    ekranowi nowej rekrutacji (jeszcze bez ``job_id``) — wtedy wołający musi
    móc czytać choć jedną rekrutację tego klienta; admin/HoR/DL/Finanse czytają
    je organizacyjnie.
    """
    if (job_id is None) == (client_id is None):
        raise HTTPException(
            status_code=422,
            detail="Podaj rekrutację albo klienta (dokładnie jedno z nich).",
        )
    if job_id is not None:
        await ensure_job_read_access(db, current_user, job_id)
        client_id = await db.scalar(select(Job.client_id).where(Job.id == job_id))
        if client_id is None:
            return []
    else:
        readable = await db.scalar(
            select(
                exists().where(
                    Job.client_id == client_id,
                    job_read_scope_clause(current_user, Job.id),
                )
            )
        )
        if not readable:
            has_jobs = await db.scalar(
                select(exists().where(Job.client_id == client_id))
            )
            if has_jobs:
                raise HTTPException(
                    status_code=403,
                    detail="Brak dostępu do rekrutacji tego klienta.",
                )
            # Klient bez rekrutacji nie ma debriefów — nie ma czego pokazać.
            return []
    rows = (
        await db.execute(
            select(InterviewQuestion)
            .where(
                InterviewQuestion.client_id == client_id,
                InterviewQuestion.source == InterviewQuestionSource.client_debrief,
            )
            .order_by(InterviewQuestion.created_at.desc(), InterviewQuestion.id.desc())
            .limit(limit)
        )
    ).scalars()
    return [
        ClientQuestionOut(id=q.id, text=q.text, created_at=q.created_at) for q in rows
    ]


@router.get(
    "/interview-cycle/client-questions/archive",
    response_model=list[ArchiveQuestionOut],
)
async def list_client_question_archive(
    current_user: RecruitmentReadAccess,
    job_id: int = Query(...),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> list[ArchiveQuestionOut]:
    """Archiwum rozmów tego klienta (0383), wybrane po technologiach roli.

    Osobna trasa, a nie pole w ``client-questions``: tamta lista to „co klient
    pytał ostatnio” i ma zostać taka sama jak przed importem archiwum.
    """
    from app.services.client_question_archive import archive_questions_for_role
    from app.services.question_suggestions import job_requirement_names

    await ensure_job_read_access(db, current_user, job_id)
    job = await db.get(Job, job_id)
    if job is None or job.client_id is None:
        return []
    matches = await archive_questions_for_role(
        db,
        client_id=job.client_id,
        requirement_names=job_requirement_names(job),
        limit=limit,
    )
    return [
        ArchiveQuestionOut(
            id=m.question.id, text=m.question.text, matched=list(m.matched)
        )
        for m in matches
    ]
