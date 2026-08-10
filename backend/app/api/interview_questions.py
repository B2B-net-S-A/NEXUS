"""Interview Questions API — CRUD + job pin/unpin/reorder + rating + suggestions.

Reguły:
- Wszystkie endpointy wymagają JWT (Depends(get_current_user)).
- Dedup po normalized_text_hash: jeśli istnieje pytanie z tym samym hashem
  w *tym samym scope* (same client_id lub global), zwracamy istniejące zamiast
  tworzyć duplikat.
- Tenant isolation: pytania z client_id != NULL nigdy nie wyciekają do
  prep-kitów innych klientów (enforced w question_suggestions.py).
- `POST /api/interview-questions` z opcjonalnym `job_id` auto-pinuje do joba.
"""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import OperationalUser, get_current_user
from app.core.database import get_db
from app.models.interview_question import (
    InterviewQuestion,
    InterviewQuestionRating,
    InterviewQuestionSeniority,
    InterviewQuestionSource,
    InterviewQuestionType,
    JobQuestion,
    JobQuestionAddedBySource,
    QuestionRatingValue,
)
from app.models.job import Job
from app.models.user import User, UserRole
from app.services.question_suggestions import suggest_questions_for_prep

router = APIRouter()

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize_hash(text: str) -> str:
    norm = _WHITESPACE_RE.sub(" ", text.strip().lower())
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()


# ─── Schemas ─────────────────────────────────────────────────────────────────


class InterviewQuestionCreate(BaseModel):
    text: str = Field(..., min_length=3, max_length=2000)
    ideal_answer: Optional[str] = None
    deal_breaker: bool = False
    competence_category_id: Optional[int] = None
    skill_tags: Optional[list[str]] = None
    seniority: Optional[InterviewQuestionSeniority] = None
    question_type: Optional[InterviewQuestionType] = None
    client_id: Optional[int] = None
    # Optional: jeśli podane, auto-pinujemy do tego joba.
    job_id: Optional[int] = None


class InterviewQuestionUpdate(BaseModel):
    text: Optional[str] = Field(None, min_length=3, max_length=2000)
    ideal_answer: Optional[str] = None
    deal_breaker: Optional[bool] = None
    competence_category_id: Optional[int] = None
    skill_tags: Optional[list[str]] = None
    seniority: Optional[InterviewQuestionSeniority] = None
    question_type: Optional[InterviewQuestionType] = None
    client_id: Optional[int] = None


class InterviewQuestionOut(BaseModel):
    id: int
    text: str
    ideal_answer: Optional[str]
    deal_breaker: bool
    competence_category_id: Optional[int]
    skill_tags: list[str]
    seniority: Optional[str]
    question_type: Optional[str]
    source: str
    client_id: Optional[int]
    created_by: Optional[int]
    up_votes: int = 0
    down_votes: int = 0


def _to_out(iq: InterviewQuestion, up: int = 0, down: int = 0) -> InterviewQuestionOut:
    return InterviewQuestionOut(
        id=iq.id,
        text=iq.text,
        ideal_answer=iq.ideal_answer,
        deal_breaker=iq.deal_breaker,
        competence_category_id=iq.competence_category_id,
        skill_tags=list(iq.skill_tags or []),
        seniority=iq.seniority.value if iq.seniority else None,
        question_type=iq.question_type.value if iq.question_type else None,
        source=iq.source.value,
        client_id=iq.client_id,
        created_by=iq.created_by,
        up_votes=up,
        down_votes=down,
    )


class PinRequest(BaseModel):
    question_id: int
    order_index: Optional[float] = None


class ReorderItem(BaseModel):
    question_id: int
    order_index: float


class ReorderRequest(BaseModel):
    items: list[ReorderItem]


class RateRequest(BaseModel):
    rating: QuestionRatingValue
    job_id: Optional[int] = None
    candidate_id: Optional[int] = None
    notes: Optional[str] = None


class JobQuestionOut(BaseModel):
    id: int
    question: InterviewQuestionOut
    is_pinned: bool
    added_by_source: str
    order_index: float


class SuggestedQuestionOut(BaseModel):
    text: str
    source_tier: str
    question_id: Optional[int]
    source_job_id: Optional[int]
    ideal_answer: Optional[str]
    deal_breaker: bool
    seniority: Optional[str]
    question_type: Optional[str]
    skill_tags: list[str]
    cosine_score: Optional[float]


# ─── Vote-count helper (pojedynczy query na listę pytań) ─────────────────────


async def _count_votes(
    db: AsyncSession, question_ids: list[int]
) -> dict[int, dict[str, int]]:
    if not question_ids:
        return {}
    result = await db.execute(
        select(
            InterviewQuestionRating.question_id,
            InterviewQuestionRating.rating,
            func.count().label("cnt"),
        )
        .where(InterviewQuestionRating.question_id.in_(question_ids))
        .group_by(InterviewQuestionRating.question_id, InterviewQuestionRating.rating)
    )
    out: dict[int, dict[str, int]] = {qid: {"up": 0, "down": 0} for qid in question_ids}
    for qid, rating, cnt in result.all():
        rating_val = rating.value if hasattr(rating, "value") else str(rating)
        out.setdefault(qid, {"up": 0, "down": 0})[rating_val] = int(cnt)
    return out


# ─── Create / Read / Update / Delete ─────────────────────────────────────────


@router.post(
    "/interview-questions",
    response_model=InterviewQuestionOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_question(
    payload: InterviewQuestionCreate,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> InterviewQuestionOut:
    # Dedup — jeśli hash już istnieje w tym samym scope, zwróć istniejące
    norm_hash = _normalize_hash(payload.text)
    if payload.client_id is None:
        dup = await db.execute(
            select(InterviewQuestion).where(
                InterviewQuestion.client_id.is_(None),
                InterviewQuestion.normalized_text_hash == norm_hash,
            )
        )
    else:
        dup = await db.execute(
            select(InterviewQuestion).where(
                InterviewQuestion.client_id == payload.client_id,
                InterviewQuestion.normalized_text_hash == norm_hash,
            )
        )
    existing = dup.scalar_one_or_none()

    if existing is None:
        iq = InterviewQuestion(
            text=payload.text.strip(),
            ideal_answer=payload.ideal_answer,
            deal_breaker=payload.deal_breaker,
            competence_category_id=payload.competence_category_id,
            skill_tags=payload.skill_tags or [],
            seniority=payload.seniority,
            question_type=payload.question_type,
            source=InterviewQuestionSource.manual,
            client_id=payload.client_id,
            normalized_text_hash=norm_hash,
            created_by=current_user.id,
        )
        db.add(iq)
        await db.flush()
    else:
        iq = existing

    # Auto-pin do joba (jeśli podano job_id)
    if payload.job_id is not None:
        job_exists = await db.execute(select(Job.id).where(Job.id == payload.job_id))
        if not job_exists.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")
        await _pin_to_job_impl(
            db=db,
            job_id=payload.job_id,
            question_id=iq.id,
            added_by_user_id=current_user.id,
            added_by_source=JobQuestionAddedBySource.manual,
            order_index=None,
        )

    await db.commit()
    await db.refresh(iq)
    votes = await _count_votes(db, [iq.id])
    v = votes.get(iq.id, {"up": 0, "down": 0})
    return _to_out(iq, up=v["up"], down=v["down"])


@router.get("/interview-questions", response_model=list[InterviewQuestionOut])
async def list_questions(
    cc_id: Optional[int] = Query(None),
    skill_tag: Optional[str] = Query(None),
    seniority: Optional[InterviewQuestionSeniority] = Query(None),
    question_type: Optional[InterviewQuestionType] = Query(None),
    client_id: Optional[int] = Query(None, description="-1 = tylko globalne"),
    q: Optional[str] = Query(None, description="Fuzzy search w tekście pytania"),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[InterviewQuestionOut]:
    stmt = select(InterviewQuestion)
    conds = []
    if cc_id is not None:
        conds.append(InterviewQuestion.competence_category_id == cc_id)
    if seniority is not None:
        conds.append(InterviewQuestion.seniority == seniority)
    if question_type is not None:
        conds.append(InterviewQuestion.question_type == question_type)
    if client_id is not None:
        if client_id == -1:
            conds.append(InterviewQuestion.client_id.is_(None))
        else:
            conds.append(InterviewQuestion.client_id == client_id)
    if q:
        conds.append(InterviewQuestion.text.ilike(f"%{q.strip()}%"))
    if skill_tag:
        conds.append(InterviewQuestion.skill_tags.contains([skill_tag.strip().lower()]))
    if conds:
        stmt = stmt.where(and_(*conds))
    stmt = stmt.order_by(desc(InterviewQuestion.created_at)).limit(limit)

    result = await db.execute(stmt)
    items = result.scalars().all()
    votes = await _count_votes(db, [i.id for i in items])
    return [
        _to_out(
            i,
            up=votes.get(i.id, {}).get("up", 0),
            down=votes.get(i.id, {}).get("down", 0),
        )
        for i in items
    ]


@router.get("/interview-questions/{question_id}", response_model=InterviewQuestionOut)
async def get_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewQuestionOut:
    iq = await db.get(InterviewQuestion, question_id)
    if not iq:
        raise HTTPException(status_code=404, detail="Nie znaleziono pytania")
    votes = await _count_votes(db, [iq.id])
    v = votes.get(iq.id, {"up": 0, "down": 0})
    return _to_out(iq, up=v["up"], down=v["down"])


@router.put("/interview-questions/{question_id}", response_model=InterviewQuestionOut)
async def update_question(
    question_id: int,
    payload: InterviewQuestionUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> InterviewQuestionOut:
    iq = await db.get(InterviewQuestion, question_id)
    if not iq:
        raise HTTPException(status_code=404, detail="Nie znaleziono pytania")

    # Autoryzacja: tylko autor lub admin edytuje
    if iq.created_by not in (None, current_user.id) and not current_user.has_role(
        UserRole.admin
    ):
        raise HTTPException(
            status_code=403,
            detail="Tylko autor pytania lub admin może edytować",
        )

    data = payload.model_dump(exclude_unset=True)
    if "text" in data and data["text"]:
        iq.text = data["text"].strip()
        iq.normalized_text_hash = _normalize_hash(iq.text)
    for field in (
        "ideal_answer",
        "deal_breaker",
        "competence_category_id",
        "skill_tags",
        "seniority",
        "question_type",
        "client_id",
    ):
        if field in data:
            setattr(iq, field, data[field])

    await db.commit()
    await db.refresh(iq)
    votes = await _count_votes(db, [iq.id])
    v = votes.get(iq.id, {"up": 0, "down": 0})
    return _to_out(iq, up=v["up"], down=v["down"])


@router.delete(
    "/interview-questions/{question_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_question(
    question_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    iq = await db.get(InterviewQuestion, question_id)
    if not iq:
        raise HTTPException(status_code=404, detail="Nie znaleziono pytania")
    if iq.created_by not in (None, current_user.id) and not current_user.has_role(
        UserRole.admin
    ):
        raise HTTPException(status_code=403, detail="Tylko autor lub admin może usunąć")
    await db.delete(iq)
    await db.commit()


# ─── Pin / Unpin / Reorder ───────────────────────────────────────────────────


async def _pin_to_job_impl(
    db: AsyncSession,
    job_id: int,
    question_id: int,
    added_by_user_id: Optional[int],
    added_by_source: JobQuestionAddedBySource,
    order_index: Optional[float],
) -> JobQuestion:
    existing = await db.execute(
        select(JobQuestion).where(
            JobQuestion.job_id == job_id, JobQuestion.question_id == question_id
        )
    )
    jq = existing.scalar_one_or_none()
    if jq is not None:
        if not jq.is_pinned:
            jq.is_pinned = True
        return jq

    # Wylicz order_index jeśli nie podany: max + 1000
    if order_index is None:
        max_q = await db.execute(
            select(func.coalesce(func.max(JobQuestion.order_index), 0.0)).where(
                JobQuestion.job_id == job_id
            )
        )
        order_index = float(max_q.scalar_one() or 0.0) + 1000.0

    jq = JobQuestion(
        job_id=job_id,
        question_id=question_id,
        is_pinned=True,
        added_by_source=added_by_source,
        added_by_user_id=added_by_user_id,
        order_index=order_index,
    )
    db.add(jq)
    await db.flush()
    return jq


@router.post(
    "/jobs/{job_id}/questions/pin",
    response_model=JobQuestionOut,
    status_code=status.HTTP_201_CREATED,
)
async def pin_question_to_job(
    job_id: int,
    payload: PinRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> JobQuestionOut:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")
    iq = await db.get(InterviewQuestion, payload.question_id)
    if not iq:
        raise HTTPException(status_code=404, detail="Nie znaleziono pytania")

    # Tenant safety: pytanie client-specific można pinować tylko do joba
    # z tym samym client_id
    if iq.client_id is not None and iq.client_id != job.client_id:
        raise HTTPException(
            status_code=403,
            detail="Pytanie klienta X nie może być przypięte do projektu klienta Y",
        )

    jq = await _pin_to_job_impl(
        db=db,
        job_id=job_id,
        question_id=payload.question_id,
        added_by_user_id=current_user.id,
        added_by_source=JobQuestionAddedBySource.manual,
        order_index=payload.order_index,
    )
    await db.commit()
    await db.refresh(jq)
    votes = await _count_votes(db, [iq.id])
    v = votes.get(iq.id, {"up": 0, "down": 0})
    return JobQuestionOut(
        id=jq.id,
        question=_to_out(iq, up=v["up"], down=v["down"]),
        is_pinned=jq.is_pinned,
        added_by_source=jq.added_by_source.value,
        order_index=jq.order_index,
    )


@router.delete(
    "/jobs/{job_id}/questions/{question_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unpin_question_from_job(
    job_id: int,
    question_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(JobQuestion).where(
            JobQuestion.job_id == job_id, JobQuestion.question_id == question_id
        )
    )
    jq = result.scalar_one_or_none()
    if not jq:
        raise HTTPException(status_code=404, detail="Pytanie nie jest przypięte")
    await db.delete(jq)
    await db.commit()


@router.patch("/jobs/{job_id}/questions/reorder", response_model=list[JobQuestionOut])
async def reorder_job_questions(
    job_id: int,
    payload: ReorderRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> list[JobQuestionOut]:
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")

    q_ids = [item.question_id for item in payload.items]
    result = await db.execute(
        select(JobQuestion)
        .where(JobQuestion.job_id == job_id, JobQuestion.question_id.in_(q_ids))
        .options(selectinload(JobQuestion.question))
    )
    links = {link.question_id: link for link in result.scalars().all()}

    for item in payload.items:
        link = links.get(item.question_id)
        if link:
            link.order_index = float(item.order_index)

    await db.commit()

    # Zwróć aktualny stan wszystkich pinned dla tego joba
    out = await db.execute(
        select(JobQuestion)
        .where(JobQuestion.job_id == job_id, JobQuestion.is_pinned.is_(True))
        .options(selectinload(JobQuestion.question))
        .order_by(JobQuestion.order_index.asc())
    )
    out_links = out.scalars().all()
    votes = await _count_votes(
        db, [link.question_id for link in out_links if link.question]
    )
    return [
        JobQuestionOut(
            id=link.id,
            question=_to_out(
                link.question,
                up=votes.get(link.question.id, {}).get("up", 0),
                down=votes.get(link.question.id, {}).get("down", 0),
            ),
            is_pinned=link.is_pinned,
            added_by_source=link.added_by_source.value,
            order_index=link.order_index,
        )
        for link in out_links
        if link.question
    ]


# ─── Rating ──────────────────────────────────────────────────────────────────


@router.post(
    "/interview-questions/{question_id}/rate",
    status_code=status.HTTP_201_CREATED,
)
async def rate_question(
    question_id: int,
    payload: RateRequest,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    iq = await db.get(InterviewQuestion, question_id)
    if not iq:
        raise HTTPException(status_code=404, detail="Nie znaleziono pytania")

    rating = InterviewQuestionRating(
        question_id=question_id,
        user_id=current_user.id,
        job_id=payload.job_id,
        candidate_id=payload.candidate_id,
        rating=payload.rating,
        notes=payload.notes,
    )
    db.add(rating)
    await db.commit()
    await db.refresh(rating)
    votes = await _count_votes(db, [question_id])
    v = votes.get(question_id, {"up": 0, "down": 0})
    return {"id": rating.id, "up_votes": v["up"], "down_votes": v["down"]}


# ─── Suggestions ─────────────────────────────────────────────────────────────


@router.get(
    "/jobs/{job_id}/suggested-questions",
    response_model=list[SuggestedQuestionOut],
)
async def get_suggested_questions(
    job_id: int,
    candidate_id: Optional[int] = Query(None),
    target_count: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[SuggestedQuestionOut]:
    """Zwraca pełny waterfall tier 1-4 z metadata (source_tier, cosine_score).

    Używany bezpośrednio przez UI "podpowiedzi pytań" oraz wewnętrznie przez
    `prep_kit.generate_prep_kit`.
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji")

    suggestions = await suggest_questions_for_prep(
        db=db, job=job, target_count=target_count
    )
    return [SuggestedQuestionOut(**s.to_dict()) for s in suggestions]


# ─── Job pinned list ─────────────────────────────────────────────────────────


@router.get("/jobs/{job_id}/questions", response_model=list[JobQuestionOut])
async def list_job_questions(
    job_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[JobQuestionOut]:
    """Lista pytań przypiętych do joba, sortowana po order_index."""
    result = await db.execute(
        select(JobQuestion)
        .where(JobQuestion.job_id == job_id)
        .options(selectinload(JobQuestion.question))
        .order_by(JobQuestion.order_index.asc())
    )
    links = result.scalars().all()
    votes = await _count_votes(
        db, [link.question_id for link in links if link.question]
    )
    return [
        JobQuestionOut(
            id=link.id,
            question=_to_out(
                link.question,
                up=votes.get(link.question.id, {}).get("up", 0),
                down=votes.get(link.question.id, {}).get("down", 0),
            ),
            is_pinned=link.is_pinned,
            added_by_source=link.added_by_source.value,
            order_index=link.order_index,
        )
        for link in links
        if link.question
    ]
