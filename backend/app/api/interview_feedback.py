"""Interview Feedback API — CRUD + czyszczenie needs_attention.

Reguły:
- Wszystkie endpointy wymagają JWT (Depends(get_current_user)).
- UNIQUE (calendar_event_id, feedback_source) — max 2 rekordy per event
  (candidate_side + client_side).
- POST/PATCH czyszczą `calendar_event.needs_attention = false` — sygnał
  "feedback zebrany".
- PATCH dopuszczalny tylko dla author_id lub usera z rolą delivery_lead /
  head_of_recruitment (DL może poprawiać feedback swojego teamu).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import (
    RecruitmentAssessmentWriteAccess,
    RecruitmentReadAccess,
    ensure_job_membership,
    ensure_optional_job_read_access,
    ensure_optional_job_membership,
    job_read_scope_clause,
)
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

router = APIRouter()


# ─── Schemas ─────────────────────────────────────────────────────────────────


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
    technical_fit: Optional[int] = Field(None, ge=1, le=5)
    soft_fit: Optional[int] = Field(None, ge=1, le=5)
    overall_fit: Optional[int] = Field(None, ge=1, le=5)
    decision: Optional[InterviewDecision] = None
    client_questions: Optional[str] = Field(None, max_length=4000)
    feedback_summary: Optional[str] = Field(None, max_length=8000)


class InterviewFeedbackOut(BaseModel):
    id: int
    calendar_event_id: int
    candidate_id: int
    job_id: Optional[int]
    author_id: Optional[int]
    feedback_source: str
    overall_impression: Optional[int]
    interest_level: Optional[str]
    candidate_questions: Optional[str]
    concerns: Optional[str]
    next_step_preference: Optional[str]
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


async def _clear_needs_attention(db: AsyncSession, calendar_event_id: int) -> None:
    """Feedback zebrany → zgaś czerwoną flagę na evencie."""
    event = await db.get(CalendarEvent, calendar_event_id)
    if event is not None and event.needs_attention:
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

    fb = InterviewFeedback(
        calendar_event_id=payload.calendar_event_id,
        candidate_id=payload.candidate_id,
        job_id=payload.job_id,
        author_id=current_user.id,
        feedback_source=payload.feedback_source,
        overall_impression=payload.overall_impression,
        interest_level=payload.interest_level,
        candidate_questions=payload.candidate_questions,
        concerns=payload.concerns,
        next_step_preference=payload.next_step_preference,
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

    await _clear_needs_attention(db, payload.calendar_event_id)
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
    await _clear_needs_attention(db, fb.calendar_event_id)
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
