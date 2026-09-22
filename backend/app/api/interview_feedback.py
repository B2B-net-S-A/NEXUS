"""Interview Feedback API — CRUD + czyszczenie needs_attention.

Reguły:
- Wszystkie endpointy wymagają JWT (Depends(get_current_user)).
- UNIQUE (calendar_event_id, feedback_source) — max 2 rekordy per event
  (candidate_side + client_side).
- POST/PATCH czyszczą `calendar_event.needs_attention = false` — sygnał
  "feedback zebrany".
- PATCH dopuszczalny tylko dla author_id lub usera z rolą delivery_lead /
  head_of_recruitment (DL może poprawiać feedback swojego teamu).
- Router stoi za sekcją Pipeline (`PIPELINE_SECTION_DEPENDENCIES`): guardy
  rolowe niżej sprawdzają rolę, nie efektywny dostęp do sekcji, więc bez tego
  rekruter z sekcją `pipeline=none` nadal czytał i zapisywał feedback przez API
  (audyt uprawnień 14.09.2026, F02).
- POST wiąże feedback z wydarzeniem dopiero po sprawdzeniu, że wołający ma
  do niego dostęp (`user_can_view_event`: właściciel, uczestnik albo rola
  z odczytem kalendarza — feedback pisze osoba, która brała udział w rozmowie)
  i że kandydat/rekrutacja z payloadu zgadzają się z wydarzeniem; pusty
  `job_id` dziedziczy `event.job_id` (audyt 14.09.2026, F01). Obcy — ani
  właściciel, ani uczestnik — dostaje 403 przed jakimkolwiek zapisem.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.calendar_access import user_can_mutate_event, user_can_view_event
from app.api.recruitment_access import (
    RecruitmentAssessmentWriteAccess,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_optional_job_read_access,
    ensure_optional_job_membership,
    job_read_scope_clause,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.calendar_event import CalendarEvent
from app.models.interview_feedback import (
    FeedbackSource,
    InterestLevel,
    InterviewDecision,
    InterviewFeedback,
    NextStepPreference,
)
from app.models.user import User, UserRole
from app.services.interview_feedback_actions import apply_post_feedback_actions

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


# ─── Schemas ─────────────────────────────────────────────────────────────────


OfferAcceptance = Literal["yes", "likely", "no", "unknown"]


class InterviewFeedbackCreate(BaseModel):
    calendar_event_id: int
    candidate_id: int
    job_id: Optional[int] = None
    feedback_source: FeedbackSource

    # candidate_side
    overall_impression: Optional[int] = Field(None, ge=1, le=5)
    interest_level: Optional[InterestLevel] = None
    candidate_questions: Optional[str] = Field(None, max_length=4000)
    concerns: Optional[str] = Field(None, max_length=4000)
    next_step_preference: Optional[NextStepPreference] = None
    # 0338: debrief po rozmowie u klienta.
    offer_acceptance: Optional[OfferAcceptance] = None
    acceptance_condition: Optional[str] = Field(None, max_length=2000)

    # client_side
    technical_fit: Optional[int] = Field(None, ge=1, le=5)
    soft_fit: Optional[int] = Field(None, ge=1, le=5)
    overall_fit: Optional[int] = Field(None, ge=1, le=5)
    decision: Optional[InterviewDecision] = None
    client_questions: Optional[str] = Field(None, max_length=4000)
    feedback_summary: Optional[str] = Field(None, max_length=8000)

    @field_validator("feedback_source")
    @classmethod
    def _normalize_source(cls, v: FeedbackSource) -> FeedbackSource:
        return v


class InterviewFeedbackUpdate(BaseModel):
    overall_impression: Optional[int] = Field(None, ge=1, le=5)
    interest_level: Optional[InterestLevel] = None
    candidate_questions: Optional[str] = Field(None, max_length=4000)
    concerns: Optional[str] = Field(None, max_length=4000)
    next_step_preference: Optional[NextStepPreference] = None
    offer_acceptance: Optional[OfferAcceptance] = None
    acceptance_condition: Optional[str] = Field(None, max_length=2000)
    technical_fit: Optional[int] = Field(None, ge=1, le=5)
    soft_fit: Optional[int] = Field(None, ge=1, le=5)
    overall_fit: Optional[int] = Field(None, ge=1, le=5)
    decision: Optional[InterviewDecision] = None
    client_questions: Optional[str] = Field(None, max_length=4000)
    feedback_summary: Optional[str] = Field(None, max_length=8000)


class InterviewFeedbackOut(BaseModel):
    id: int
    # NULL od migracji 0278: werdykty hiring managera zapisywane z karty
    # rekrutacji (`POST /jobs/{id}/hiring-manager-feedback`) nie mają
    # wydarzenia w kalendarzu. `int` wywalałby serializację CAŁEJ listy
    # (`ResponseValidationError` → 500) przy pierwszym takim wierszu.
    calendar_event_id: Optional[int]
    candidate_id: int
    job_id: Optional[int]
    author_id: Optional[int]
    feedback_source: str
    overall_impression: Optional[int]
    interest_level: Optional[str]
    candidate_questions: Optional[str]
    concerns: Optional[str]
    next_step_preference: Optional[str]
    offer_acceptance: Optional[str] = None
    acceptance_condition: Optional[str] = None
    technical_fit: Optional[int]
    soft_fit: Optional[int]
    overall_fit: Optional[int]
    decision: Optional[str]
    client_questions: Optional[str]
    feedback_summary: Optional[str]


def _to_out(fb: InterviewFeedback) -> InterviewFeedbackOut:
    def _enum_value(x):
        return x.value if x is not None else None

    return InterviewFeedbackOut(
        id=fb.id,
        calendar_event_id=fb.calendar_event_id,
        candidate_id=fb.candidate_id,
        job_id=fb.job_id,
        author_id=fb.author_id,
        feedback_source=fb.feedback_source.value,
        overall_impression=fb.overall_impression,
        interest_level=_enum_value(fb.interest_level),
        candidate_questions=fb.candidate_questions,
        concerns=fb.concerns,
        next_step_preference=_enum_value(fb.next_step_preference),
        offer_acceptance=fb.offer_acceptance,
        acceptance_condition=fb.acceptance_condition,
        technical_fit=fb.technical_fit,
        soft_fit=fb.soft_fit,
        overall_fit=fb.overall_fit,
        decision=_enum_value(fb.decision),
        client_questions=fb.client_questions,
        feedback_summary=fb.feedback_summary,
    )


def _can_edit(user: User, fb: InterviewFeedback) -> bool:
    """Author, DL, HR, lub admin mogą edytować.

    M4 PR-01: ``has_any_role`` zamiast porównania primary ``user.role`` —
    hybrydowa persona (np. TAC z dodatkową rolą delivery_lead) przechodzi.
    """
    if fb.author_id == user.id:
        return True
    return user.has_any_role(
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
        UserRole.admin,
    )


def _bind_feedback_to_event(
    event: CalendarEvent,
    user: User,
    *,
    job_id: Optional[int],
    candidate_id: int,
) -> Optional[int]:
    """Zanim feedback wskaże wydarzenie: kto może i o kim/o czym ono jest.

    Do 09.2026 `create_feedback` sprawdzał wyłącznie ISTNIENIE wydarzenia:
    dowolny operacyjny użytkownik mógł podpiąć feedback pod cudze spotkanie
    (i zgasić na nim `needs_attention`), a `candidate_id`/`job_id` z payloadu
    nie musiały mieć nic wspólnego z tym, kogo wydarzenie dotyczy — feedback
    z rozmowy A lądował pod kandydatem B.

    Zwraca rekrutację, pod którą feedback ma się zapisać: `job_id` z payloadu
    albo — gdy payload go nie niesie — `event.job_id`. Wydarzenie bez
    rekrutacji/kandydata (kolumny są nullable) niczego nie wymusza.
    """
    # Autoryzacja PRZED spójnością: obcy nie ma się dowiedzieć, jakiej
    # rekrutacji i jakiego kandydata dotyczy spotkanie. Feedback pisze osoba,
    # która w spotkaniu BRAŁA UDZIAŁ — także uczestnik cudzego wydarzenia
    # (rekruter na rozmowie zorganizowanej przez DL), stąd `view`, nie `mutate`.
    # Bramki sekcji, roli i członkostwa w rekrutacji działają obok.
    if not user_can_view_event(event, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do tego wydarzenia w kalendarzu",
        )
    if event.candidate_id is not None and event.candidate_id != candidate_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Kandydat w feedbacku nie zgadza się z kandydatem wydarzenia",
        )
    if event.job_id is None:
        return job_id
    if job_id is not None and job_id != event.job_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Rekrutacja w feedbacku nie zgadza się z rekrutacją wydarzenia",
        )
    return event.job_id


async def _clear_needs_attention(db: AsyncSession, event: CalendarEvent) -> None:
    """Feedback zebrany → zgaś czerwoną flagę na evencie."""
    if event.needs_attention:
        event.needs_attention = False
        await db.flush()


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "/interview-feedback",
    response_model=InterviewFeedbackOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_feedback(
    payload: InterviewFeedbackCreate,
    current_user: RecruitmentAssessmentWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> InterviewFeedbackOut:
    # P1-PIPE-01: feedback tied to a job is a pipeline ingress — members only.
    # Checked before the event lookup so a non-member of the job learns nothing
    # about the referenced event. Job-less feedback (job_id omitted) is not
    # scope-gated: there is no job to scope it to.
    if payload.job_id is not None:
        await ensure_job_membership(db, current_user, payload.job_id)

    event = await db.get(CalendarEvent, payload.calendar_event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono eventu")
    job_id = _bind_feedback_to_event(
        event,
        current_user,
        job_id=payload.job_id,
        candidate_id=payload.candidate_id,
    )
    # Rekrutacja odziedziczona z wydarzenia też przechodzi bramkę członkostwa —
    # payload bez `job_id` nie może być drogą obok P1-PIPE-01.
    if job_id is not None and job_id != payload.job_id:
        await ensure_job_membership(db, current_user, job_id)

    fb = InterviewFeedback(
        calendar_event_id=payload.calendar_event_id,
        candidate_id=payload.candidate_id,
        job_id=job_id,
        author_id=current_user.id,
        feedback_source=payload.feedback_source,
        overall_impression=payload.overall_impression,
        interest_level=payload.interest_level,
        candidate_questions=payload.candidate_questions,
        concerns=payload.concerns,
        next_step_preference=payload.next_step_preference,
        offer_acceptance=payload.offer_acceptance,
        acceptance_condition=payload.acceptance_condition,
        technical_fit=payload.technical_fit,
        soft_fit=payload.soft_fit,
        overall_fit=payload.overall_fit,
        decision=payload.decision,
        client_questions=payload.client_questions,
        feedback_summary=payload.feedback_summary,
    )
    db.add(fb)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail=(
                "Feedback dla tego eventu i strony (candidate/client) już istnieje. "
                "Użyj PATCH aby zaktualizować."
            ),
        )

    await _clear_needs_attention(db, event)
    # Auto-akcje (advance → suggest_next_step, reject/dead → zamknij + pool)
    try:
        await apply_post_feedback_actions(db, fb)
    except Exception:  # noqa: BLE001
        # Auto-akcje są best-effort — log i jedziemy dalej z zapisem feedbacku.
        import logging

        logging.getLogger(__name__).exception(
            "apply_post_feedback_actions failed for feedback id=%s", fb.id
        )
    await db.commit()
    await db.refresh(fb)
    return _to_out(fb)


@router.get(
    "/interview-feedback",
    response_model=list[InterviewFeedbackOut],
)
async def list_feedback(
    current_user: RecruitmentReadAccess,
    calendar_event_id: Optional[int] = Query(None),
    candidate_id: Optional[int] = Query(None),
    job_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[InterviewFeedbackOut]:
    # Resource scope: bez tego `GET /interview-feedback` BEZ filtrów zwracał
    # ostatnie 200 feedbacków ze WSZYSTKICH rekrutacji — czyli oceny kandydatów
    # z ofert, do których wołający nie należy. Zawężamy zapytanie zamiast
    # odrzucać request, żeby trasa dalej działała dla swoich rekrutacji.
    stmt = select(InterviewFeedback).where(
        job_read_scope_clause(current_user, InterviewFeedback.job_id)
    )
    if calendar_event_id is not None:
        stmt = stmt.where(InterviewFeedback.calendar_event_id == calendar_event_id)
    if candidate_id is not None:
        stmt = stmt.where(InterviewFeedback.candidate_id == candidate_id)
    if job_id is not None:
        stmt = stmt.where(InterviewFeedback.job_id == job_id)
    stmt = stmt.order_by(InterviewFeedback.created_at.desc()).limit(200)
    rows = (await db.execute(stmt)).scalars().all()
    return [_to_out(r) for r in rows]


@router.get(
    "/interview-feedback/{feedback_id}",
    response_model=InterviewFeedbackOut,
)
async def get_feedback(
    feedback_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> InterviewFeedbackOut:
    fb = await db.get(InterviewFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback nie istnieje")
    await ensure_optional_job_read_access(db, current_user, fb.job_id)
    return _to_out(fb)


@router.patch(
    "/interview-feedback/{feedback_id}",
    response_model=InterviewFeedbackOut,
)
async def update_feedback(
    feedback_id: int,
    payload: InterviewFeedbackUpdate,
    current_user: RecruitmentAssessmentWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> InterviewFeedbackOut:
    fb = await db.get(InterviewFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback nie istnieje")
    await ensure_optional_job_membership(db, current_user, fb.job_id)
    if not _can_edit(current_user, fb):
        raise HTTPException(
            status_code=403, detail="Brak uprawnień do edycji tego feedbacku"
        )

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(fb, field, value)

    await db.flush()
    # Werdykt HM z karty rekrutacji nie ma wydarzenia — nie ma czego odznaczać.
    # PATCH nie zmienia `calendar_event_id`, więc wydarzenie zostało uzgodnione
    # przy zapisie; flagę gasi tylko autor feedbacku albo ktoś, kto może
    # mutować wydarzenie. DL/HoR poprawiający cudzy feedback (`_can_edit`)
    # zapisuje treść, ale nie dotyka cudzego spotkania — wiersz sprzed tej
    # bramki mógł wskazywać obce wydarzenie.
    if fb.calendar_event_id is not None:
        event = await db.get(CalendarEvent, fb.calendar_event_id)
        if event is not None and (
            fb.author_id == current_user.id
            or user_can_mutate_event(event, current_user)
        ):
            await _clear_needs_attention(db, event)
    try:
        await apply_post_feedback_actions(db, fb)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception(
            "apply_post_feedback_actions failed for feedback id=%s", fb.id
        )
    await db.commit()
    await db.refresh(fb)
    return _to_out(fb)


@router.delete(
    "/interview-feedback/{feedback_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_feedback(
    feedback_id: int,
    current_user: RecruitmentAssessmentWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    fb = await db.get(InterviewFeedback, feedback_id)
    if fb is None:
        raise HTTPException(status_code=404, detail="Feedback nie istnieje")
    await ensure_optional_job_membership(db, current_user, fb.job_id)
    if not _can_edit(current_user, fb):
        raise HTTPException(status_code=403, detail="Brak uprawnień do usunięcia")
    await db.delete(fb)
    await db.commit()
