# UWAGA: bez `from __future__ import annotations` — `@limiter.limit` na
# module z PEP 563 zamienia `Annotated` guardy w parametry query (slowapi #579).
"""Przepięcie → podpowiedzi Luny w arkuszu screeningu (Pipeline v4, 23.09.2026).

Dwie trasy obok `…/stages/{id}/screening` z `pipeline.py`:

* ``GET …/screening/reassign-context`` — skąd osoba przyszła (rekrutacja
  źródłowa, data, liczba odpowiedzi). Bez modelu, więc UI może pokazać baner
  bez kosztu. Bramka jak odczyt arkusza (`CandidatePIIAccess` + odczyt
  rekrutacji).
* ``POST …/screening/reassign-suggestions`` — wywołanie modelu. Bramka jak
  zapis arkusza (`RecruiterPlus` + członkostwo w rekrutacji). Niczego nie
  zapisuje; odpowiedź z awarią modelu to 200 z ``available: false``.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidatePIIAccess
from app.api.deps import RecruiterPlus, get_db
from app.api.recruitment_access import ensure_job_membership, ensure_job_read_access
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.recruitment_pipeline import CandidateStage
from app.services import screening_reassign

router = APIRouter(prefix="/pipeline", dependencies=PIPELINE_SECTION_DEPENDENCIES)


async def _stage_or_404(db: AsyncSession, stage_id: int) -> CandidateStage:
    stage = await db.scalar(select(CandidateStage).where(CandidateStage.id == stage_id))
    if stage is None:
        raise HTTPException(404, "Nie znaleziono etapu kandydata.")
    return stage


@router.get("/stages/{stage_id}/screening/reassign-context")
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_reassign_context(
    request: Request,
    stage_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> dict:
    stage = await _stage_or_404(db, stage_id)
    await ensure_job_read_access(db, current_user, stage.job_id)
    ctx, denied = await screening_reassign.accessible_context(
        db, candidate_id=stage.candidate_id, job_id=stage.job_id, user=current_user
    )
    return {
        "stage_id": stage.id,
        **screening_reassign.context_payload(ctx, denied=denied),
    }


@router.post("/stages/{stage_id}/screening/reassign-suggestions")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def post_reassign_suggestions(
    request: Request,
    stage_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    stage = await _stage_or_404(db, stage_id)
    await ensure_job_membership(db, current_user, stage.job_id)
    result = await screening_reassign.suggest_answers(
        db, stage=stage, user=current_user
    )
    return {"stage_id": stage_id, **result}
