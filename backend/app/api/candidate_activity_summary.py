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
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.ai_quota import AIQuotaExceeded
from app.services.candidate_activity_summary_service import (
    CandidateActivitySummaryBusy,
    CandidateActivitySummaryLLMError,
    CandidateActivitySummaryNotFound,
    CandidateActivitySummaryState,
    get_or_generate,
    get_summary_state,
)

router = APIRouter()


class CandidateActivitySummaryOut(BaseModel):
    candidate_id: int
    # None = note not generated yet (FE shows the "Wygeneruj" empty state).
    summary: Optional[str] = None
    model: Optional[str] = None
    generated_at: Optional[datetime] = None
    # Version of sources used by the stored prose and the version visible now.
    source_version: Optional[str] = None
    current_source_version: str
    is_stale: bool = False
    visibility_scope_hash: str
    source_manifest: dict[str, Any]
    # Only meaningful on the refresh endpoint: False = history unchanged,
    # cached note served without a paid LLM call.
    refreshed: Optional[bool] = None


def _serialize(
    candidate_id: int,
    state: CandidateActivitySummaryState,
    *,
    refreshed: Optional[bool] = None,
) -> CandidateActivitySummaryOut:
    row = state.row
    return CandidateActivitySummaryOut(
        candidate_id=candidate_id,
        summary=row.summary if row else None,
        model=row.model if row else None,
        generated_at=row.generated_at if row else None,
        source_version=row.source_version if row else None,
        current_source_version=state.current_source_version,
        is_stale=state.is_stale,
        visibility_scope_hash=state.visibility_scope_hash,
        source_manifest=(row.source_manifest if row else state.current_source_manifest),
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
    try:
        state = await get_summary_state(
            candidate_id,
            db,
            user=current_user,
        )
    except CandidateActivitySummaryNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except AIQuotaExceeded as exc:
        # Serve and generate use the same kill-switch.  A disabled feature must
        # never continue exposing an older cached note.
        raise HTTPException(status_code=503, detail=str(exc.reason)) from exc
    return _serialize(candidate_id, state)


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
        state, generated = await get_or_generate(
            candidate_id,
            db,
            user=current_user,
            user_id=current_user.id,
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
    except CandidateActivitySummaryBusy as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
            headers={"Retry-After": "3"},
        ) from exc
    return _serialize(candidate_id, state, refreshed=generated)
