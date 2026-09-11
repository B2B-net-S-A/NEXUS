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
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_justification import CandidateMatchJustification
from app.services.ai_quota import AIQuotaExceeded
from app.services.match_justification_service import (
    MatchJustificationLLMError,
    MatchJustificationNotFound,
    display_fit,
    get_cached,
    get_or_generate,
    notes_gap_warnings_from_extracted,
)

from app.api.section_access import SOURCING_SECTION_DEPENDENCIES

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


class NotesGapWarning(BaseModel):
    """Brak potwierdzony w notatce rekruterskiej, pokrywający się z wymaganiem
    oferty. Liczony deterministycznie per request (nigdy przez LLM i poza
    cache'em prozy) — patrz `notes_gap_warnings`."""

    skill: str
    evidence: Optional[str] = None


class MatchJustificationOut(BaseModel):
    candidate_id: int
    job_id: int
    job_title: Optional[str] = None
    # Canonical base fit under the viewer's profile — the number C2 and the
    # kanban ring show for this pair. None = no verified semantic measurement
    # (see ``score_measurement``); never a substitute number.
    score: Optional[int] = None
    score_measurement: str = "measured"
    summary: str
    pros: list[str]
    watchouts: list[str]
    notes_warnings: list[NotesGapWarning] = Field(default_factory=list)
    model: Optional[str] = None
    rating: Optional[int] = None
    rating_comment: Optional[str] = None
    generated_at: Optional[datetime] = None


class ScoringFeedbackIn(BaseModel):
    # -1 = kciuk w dół, +1 = kciuk w górę, 0 = reset oceny.
    rating: int = Field(..., ge=-1, le=1)
    comment: Optional[str] = Field(default=None, max_length=1000)


def _serialize(
    row: CandidateMatchJustification,
    job_title: Optional[str],
    notes_warnings: Optional[list[dict]] = None,
    *,
    fit: tuple[Optional[int], str],
) -> MatchJustificationOut:
    # `row.score` (the legacy composite the prose was generated from) is
    # deliberately NOT the displayed number any more — see `display_fit`.
    score, measurement = fit
    return MatchJustificationOut(
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        job_title=job_title,
        score=score,
        score_measurement=measurement,
        summary=row.summary,
        pros=list(row.pros or []),
        watchouts=list(row.watchouts or []),
        notes_warnings=[NotesGapWarning(**w) for w in (notes_warnings or [])],
        model=row.model,
        rating=row.rating,
        rating_comment=row.rating_comment,
        generated_at=row.updated_at,
    )


async def _notes_warnings_for(
    candidate_id: int, job_id: int, db: AsyncSession
) -> tuple[Optional[str], list[dict]]:
    """(job_title, deterministyczne ostrzeżenia z notatek) dla serializacji.

    Jedno miejsce dla GET i POST /feedback — rozjazd oznaczałby, że ta sama
    para (kandydat, oferta) raz pokazuje ostrzeżenia, a raz nie.

    Z kandydata pobieramy WYŁĄCZNIE ``cv_extracted_data`` — pełny wiersz ORM
    ciągnąłby też ``raw_cv_text`` (Text, potrafi mieć megabajty) przy każdym
    wyświetleniu uzasadnienia. Job idzie w całości, bo fallback Championa
    czyta ``champion_profile``/``requirements``/``description``.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if job is None:
        return None, []
    extracted = await db.scalar(
        select(Candidate.cv_extracted_data).where(Candidate.id == candidate_id)
    )
    if not isinstance(extracted, dict) or "_notes_insights" not in extracted:
        return job.title, []
    return job.title, notes_gap_warnings_from_extracted(extracted, job)


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
    # Read once, up front: the generation path may roll this request's session
    # back (concurrent first view), which expires every object loaded through
    # it — `current_user` included.
    user_id = current_user.id
    try:
        row = await get_or_generate(
            candidate_id, job_id, db, user_id=user_id, force=refresh
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

    # Own session inside, never raises: a failed measurement is a ring without
    # a number ("ocena niepełna"), not a failed tab.
    fit = await display_fit(candidate_id, job_id, user_id=user_id)
    job_title, warnings = await _notes_warnings_for(candidate_id, job_id, db)
    return _serialize(row, job_title, warnings, fit=fit)


@router.post(
    "/{candidate_id}/scoring/{job_id}/feedback",
    response_model=MatchJustificationOut,
)
# Each response measures canonical fit on demand (query embedding + exact
# vector lookup), so the thumbs are metered like the other on-demand scoring.
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def rate_scoring_justification(
    request: Request,
    candidate_id: int,
    job_id: int,
    payload: ScoringFeedbackIn,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> MatchJustificationOut:
    """Record "Oceń ten scoring" feedback on an existing justification."""
    user_id = current_user.id
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
        row.rated_by = user_id
        row.rated_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(row)

    # The response replaces the tab's data, so it carries the same number as
    # the GET — measured in its own session, never failing the rating.
    fit = await display_fit(candidate_id, job_id, user_id=user_id)
    job_title, warnings = await _notes_warnings_for(candidate_id, job_id, db)
    return _serialize(row, job_title, warnings, fit=fit)
