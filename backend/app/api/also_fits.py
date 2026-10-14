# UWAGA: bez `from __future__ import annotations` — moduł ma `@limiter.limit`
# (slowapi #579: PEP 563 zamienia parametry `Annotated` w parametry query → 422).
"""„Pasuje też do” — inne rekrutacje dla osoby dodanej właśnie do rekrutacji.

Okno „Kandydaci do dodania” woła tę trasę zaraz po „+ Dodaj” (decyzja Artura
14.10.2026, D1). Reguła i koszt opisane w :mod:`app.services.also_fits`.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.api.recruitment_access import ensure_job_read_access, job_read_scope_clause
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.also_fits import also_fits_for_candidate

router = APIRouter()


class AlsoFitsJobOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    score: int
    matching_must: list[str] = []
    gap_must: list[str] = []


class AlsoFitsResponse(BaseModel):
    candidate_id: int
    from_job_id: int
    status: str
    jobs: list[AlsoFitsJobOut]


@router.get(
    "/candidates/{candidate_id}/also-fits",
    response_model=AlsoFitsResponse,
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
# Jedno wywołanie = jedno zapytanie wektorowe + pełna ocena kilku rekrutacji;
# okno pyta raz na dodaną osobę, więc to sufit dla zapętlonego klienta.
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def candidate_also_fits(
    request: Request,
    candidate_id: int,
    current_user: CandidateSearchAccess,
    from_job_id: int = Query(..., gt=0),
    db: AsyncSession = Depends(get_db),
) -> AlsoFitsResponse:
    """Najwyżej 3 inne rekrutacje w pracy, do których ta osoba pasuje (≥ 70)."""
    await ensure_job_read_access(db, current_user, from_job_id)
    candidate = await db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej osoby.")
    result = await also_fits_for_candidate(
        db,
        candidate=candidate,
        from_job_id=from_job_id,
        profile_user_id=current_user.id,
        scope_clause=job_read_scope_clause(current_user, Job.id),
    )
    return AlsoFitsResponse(
        candidate_id=candidate_id,
        from_job_id=from_job_id,
        status=result.status,
        jobs=[
            AlsoFitsJobOut(
                job_id=j.job_id,
                title=j.title,
                client_name=j.client_name,
                score=j.score,
                matching_must=list(j.matching_must),
                gap_must=list(j.gap_must),
            )
            for j in result.jobs
        ],
    )
