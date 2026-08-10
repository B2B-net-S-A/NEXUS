"""AI scoring justification API — powers the candidate "Dopasowanie" tab.

Endpoints (mounted under /api/candidates):
  GET  /{candidate_id}/scoring/{job_id}          → prose justification (cached or
                                                    freshly generated)
  POST /{candidate_id}/scoring/{job_id}/feedback → "Oceń ten scoring" thumbs

The heavy lifting (score computation, caching, the paid LLM call and its quota
gate) lives in ``match_justification_service``; this module is a thin transport
layer that maps domain errors to HTTP status codes.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia
# adnotacje FastAPI w ForwardRef i wywala app.openapi() na Annotated
# guardach (OperationalUser); ten sam trap co slowapi #579.

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.job import Job
from app.models.match_justification import CandidateMatchJustification
from app.services.ai_quota import AIQuotaExceeded
from app.services.match_justification_service import (
    MatchJustificationLLMError,
    MatchJustificationNotFound,
    get_cached,
    get_or_generate,
)

router = APIRouter()


class MatchJustificationOut(BaseModel):
    candidate_id: int
    job_id: int
    job_title: Optional[str] = None
    score: int
    summary: str
    pros: list[str]
    watchouts: list[str]
    model: Optional[str] = None
    rating: Optional[int] = None
    rating_comment: Optional[str] = None
    generated_at: Optional[datetime] = None


class ScoringFeedbackIn(BaseModel):
    # -1 = kciuk w dół, +1 = kciuk w górę, 0 = reset oceny.
    rating: int = Field(..., ge=-1, le=1)
    comment: Optional[str] = Field(default=None, max_length=1000)


def _serialize(
    row: CandidateMatchJustification, job_title: Optional[str]
) -> MatchJustificationOut:
    return MatchJustificationOut(
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        job_title=job_title,
        score=row.score,
        summary=row.summary,
        pros=list(row.pros or []),
        watchouts=list(row.watchouts or []),
        model=row.model,
        rating=row.rating,
        rating_comment=row.rating_comment,
        generated_at=row.updated_at,
    )


@router.get("/{candidate_id}/scoring/{job_id}", response_model=MatchJustificationOut)
@limiter.limit("20/minute")
async def get_scoring_justification(
    request: Request,
    candidate_id: int,
    job_id: int,
    # M3-SEC-01/M3-COST-01: cache-miss uruchamia PŁATNE wywołanie Claude
    # (a `refresh=true` wymusza je zawsze) — read-only viewer (`user`,
    # QC/klient) nie może generować kosztu ani czytać wewnętrznych ocen AI.
    current_user: OperationalUser,
    refresh: bool = Query(
        False, description="Wymuś regenerację uzasadnienia (nowe wywołanie AI)."
    ),
    db: AsyncSession = Depends(get_db),
) -> MatchJustificationOut:
    """AI justification of the (candidate, job) match score. Cached per pair;
    regenerates on ``refresh`` or when the underlying inputs change."""
    try:
        row = await get_or_generate(
            candidate_id, job_id, db, user_id=current_user.id, force=refresh
        )
    except MatchJustificationNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIQuotaExceeded as exc:
        # AI globally off / feature disabled / monthly limit hit.
        raise HTTPException(status_code=503, detail=str(exc.reason)) from exc
    except MatchJustificationLLMError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Nie udało się wygenerować uzasadnienia AI: {exc}",
        ) from exc

    job_title = await db.scalar(select(Job.title).where(Job.id == job_id))
    return _serialize(row, job_title)


@router.post(
    "/{candidate_id}/scoring/{job_id}/feedback",
    response_model=MatchJustificationOut,
)
async def rate_scoring_justification(
    candidate_id: int,
    job_id: int,
    payload: ScoringFeedbackIn,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> MatchJustificationOut:
    """Record "Oceń ten scoring" feedback on an existing justification."""
    row = await get_cached(candidate_id, job_id, db)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="Najpierw wygeneruj uzasadnienie dla tej pary kandydat–rekrutacja.",
        )

    if payload.rating == 0:
        row.rating = None
        row.rating_comment = None
        row.rated_by = None
        row.rated_at = None
    else:
        row.rating = payload.rating
        row.rating_comment = (payload.comment or "").strip() or None
        row.rated_by = current_user.id
        row.rated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(row)

    job_title = await db.scalar(select(Job.title).where(Job.id == job_id))
    return _serialize(row, job_title)
