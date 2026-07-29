"""AI activity-summary API — powers the "Podsumowanie aktywności" card.

Endpoints (mounted under /api/candidates):
  GET  /{candidate_id}/activity-summary          → cached note (never generates,
                                                    so opening a profile is free)
  POST /{candidate_id}/activity-summary/refresh  → "Aktualizuj notatkę": re-gather
                                                    the history and regenerate only
                                                    when it actually changed

The heavy lifting (history gathering, the paid LLM call and its quota gate)
lives in ``candidate_activity_summary_service``; this module is a thin
transport layer that maps domain errors to HTTP status codes.
"""

# UWAGA: bez `from __future__ import annotations` — PEP 563 zamienia
# adnotacje FastAPI w ForwardRef i wywala app.openapi() na Annotated
# guardach (OperationalUser); ten sam trap co slowapi #579.

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.candidate import Candidate
from app.models.candidate_activity_summary import CandidateActivitySummary
from app.services.ai_quota import AIQuotaExceeded
from app.services.candidate_activity_summary_service import (
    CandidateActivitySummaryLLMError,
    CandidateActivitySummaryNotFound,
    get_cached,
    get_or_generate,
)

router = APIRouter()


class CandidateActivitySummaryOut(BaseModel):
    candidate_id: int
    # None = note not generated yet (FE shows the "Wygeneruj" empty state).
    summary: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[datetime] = None
    # Only meaningful on the refresh endpoint: False = history unchanged,
    # cached note served without a paid LLM call.
    refreshed: Optional[bool] = None


def _serialize(
    candidate_id: int,
    row: Optional[CandidateActivitySummary],
    *,
    refreshed: Optional[bool] = None,
) -> CandidateActivitySummaryOut:
    if row is None:
        return CandidateActivitySummaryOut(candidate_id=candidate_id)
    return CandidateActivitySummaryOut(
        candidate_id=candidate_id,
        summary=row.summary,
        model=row.model,
        generated_at=row.generated_at,
        refreshed=refreshed,
    )


@router.get(
    "/{candidate_id}/activity-summary",
    response_model=CandidateActivitySummaryOut,
)
async def get_activity_summary(
    candidate_id: int,
    # Wewnętrzna notatka AI o historii kandydata — read-only viewer (`user`,
    # QC/klient) nie powinien jej czytać, spójnie z endpointem scoringu.
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CandidateActivitySummaryOut:
    """Cached activity note. Never triggers a (paid) generation — profile
    views stay free; use the refresh endpoint to (re)generate."""
    row = await get_cached(candidate_id, db)
    if row is None:
        # Only the empty-cache path needs the existence probe: a stored note
        # already proves the candidate exists (FK), so the common cached read
        # stays a single query.
        exists = await db.scalar(
            select(Candidate.id).where(Candidate.id == candidate_id)
        )
        if exists is None:
            raise HTTPException(status_code=404, detail="Kandydat nie istnieje")
    return _serialize(candidate_id, row)


@router.post(
    "/{candidate_id}/activity-summary/refresh",
    response_model=CandidateActivitySummaryOut,
)
@limiter.limit("10/minute")
async def refresh_activity_summary(
    request: Request,
    candidate_id: int,
    # Cache-miss uruchamia PŁATNE wywołanie Claude — ta sama bariera ról co
    # przy scoringu (M3-SEC-01/M3-COST-01).
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> CandidateActivitySummaryOut:
    """ "Aktualizuj notatkę": re-gather the candidate history and regenerate
    the note. If nothing changed since the last generation, the cached note is
    returned (``refreshed=false``) without spending an AI call."""
    try:
        row, generated = await get_or_generate(
            candidate_id, db, user_id=current_user.id
        )
    except CandidateActivitySummaryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIQuotaExceeded as exc:
        # AI globally off / feature disabled / monthly limit hit.
        raise HTTPException(status_code=503, detail=str(exc.reason)) from exc
    except CandidateActivitySummaryLLMError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Nie udało się wygenerować podsumowania AI: {exc}",
        ) from exc
    return _serialize(candidate_id, row, refreshed=generated)
