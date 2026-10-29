# UWAGA: bez `from __future__ import annotations` — moduł ma `@limiter.limit`
# (slowapi #579: PEP 563 zamienia parametry `Annotated` w parametry query → 422).
"""„Pasuje też do” — inne rekrutacje dla osoby dodanej właśnie do rekrutacji.

Okno „Kandydaci do dodania” woła tę trasę zaraz po „+ Dodaj” (decyzja Artura
14.10.2026, D1). Reguła i koszt opisane w :mod:`app.services.also_fits`.
"""

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.api.recruitment_access import (
    ensure_job_membership,
    ensure_job_read_access,
    job_read_scope_clause,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.also_fits import (
    SEARCH_LIMIT,
    SOURCE_OUR_CONSULTANT,
    also_fits_for_candidate,
    returning_consultant,
    search_open_jobs,
)

router = APIRouter()


class AlsoFitsJobOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    client_reference: Optional[str] = None
    score: int
    matching_must: list[str] = []
    gap_must: list[str] = []


class AlsoFitsResponse(BaseModel):
    candidate_id: int
    from_job_id: int
    status: str
    jobs: list[AlsoFitsJobOut]
    #: „nasz konsultant” — osoba z decyzją „przekaż do front office” (R2, 22.10.2026).
    source: Optional[Literal["our_consultant"]] = None
    #: „Wraca na rynek DD.MM”; ``None`` przy ``source`` = data nieznana.
    returns_to_market_on: Optional[date] = None


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
    returning = await returning_consultant(db, candidate_id, today=business_today())
    return AlsoFitsResponse(
        candidate_id=candidate_id,
        from_job_id=from_job_id,
        status=result.status,
        jobs=[
            AlsoFitsJobOut(
                job_id=j.job_id,
                title=j.title,
                client_name=j.client_name,
                client_reference=j.client_reference,
                score=j.score,
                matching_must=list(j.matching_must),
                gap_must=list(j.gap_must),
            )
            for j in result.jobs
        ],
        source=SOURCE_OUR_CONSULTANT if returning is not None else None,
        returns_to_market_on=returning.returns_on if returning is not None else None,
    )


class ManualJobOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    client_reference: Optional[str] = None
    delivery_lead_name: Optional[str] = None
    #: Rekruter jest w zespole — ta sama reguła co pary „Screening dla”
    #: (``joint-context``): tylko wtedy rekrutacja wchodzi do wspólnej rozmowy.
    joinable: bool


@router.get(
    "/candidates/{candidate_id}/also-fits/search",
    response_model=list[ManualJobOut],
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
# Pole z opóźnieniem 250 ms — jedno zapytanie na frazę; sufit jak trasa obok.
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def candidate_also_fits_search(
    request: Request,
    candidate_id: int,
    current_user: CandidateSearchAccess,
    from_job_id: int = Query(..., gt=0),
    q: str = Query("", max_length=120),
    db: AsyncSession = Depends(get_db),
) -> list[ManualJobOut]:
    """„+ Dodaj inną rekrutację” w „Screening dla” (29.10.2026).

    Otwarte rekrutacje firmy bez tej osoby, po nazwie, numerze u klienta,
    kliencie i id. Rekrutacje z zespołu patrzącego na górze.
    """
    await ensure_job_read_access(db, current_user, from_job_id)
    if await db.get(Candidate, candidate_id) is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej osoby.")
    hits = await search_open_jobs(
        db,
        candidate_id=candidate_id,
        from_job_id=from_job_id,
        phrase=q,
        scope_clause=job_read_scope_clause(current_user, Job.id),
    )
    rows: list[ManualJobOut] = []
    for hit in hits:
        try:
            await ensure_job_membership(db, current_user, hit.job_id)
            joinable = True
        except HTTPException:
            joinable = False
        rows.append(
            ManualJobOut(
                job_id=hit.job_id,
                title=hit.title,
                client_name=hit.client_name,
                client_reference=hit.client_reference,
                delivery_lead_name=hit.delivery_lead_name,
                joinable=joinable,
            )
        )
    # Stabilnie: kolejność z bazy (najnowsze) w obrębie każdej grupy.
    rows.sort(key=lambda r: not r.joinable)
    return rows[:SEARCH_LIMIT]
