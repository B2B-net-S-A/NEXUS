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

router = APIRouter()

_CONTAINMENT_DETAIL = (
    "Podsumowanie aktywności AI jest tymczasowo wyłączone do czasu "
    "bezpiecznej regeneracji cache."
)


class CandidateActivitySummaryOut(BaseModel):
    candidate_id: int
    # None = note not generated yet (FE shows the "Wygeneruj" empty state).
    summary: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[datetime] = None
    # Only meaningful on the refresh endpoint: False = history unchanged,
    # cached note served without a paid LLM call.
    refreshed: Optional[bool] = None


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
    """Fail closed while legacy cache entries have no visibility scope.

    Revision 0204 created one shared cache row per candidate. Those rows can
    contain financial facts and data from recruitments that are not visible to
    the current user. Until scope-aware cache keys and a financial-content
    policy are deployed, the API deliberately behaves like an empty cache.
    """
    exists = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if exists is None:
        raise HTTPException(status_code=404, detail="Kandydat nie istnieje")
    return CandidateActivitySummaryOut(candidate_id=candidate_id)


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
    """Block generation while the only available cache format is unscoped."""
    raise HTTPException(status_code=503, detail=_CONTAINMENT_DETAIL)
