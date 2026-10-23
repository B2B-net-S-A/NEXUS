"""Zakładka „Podobni” na profilu kandydata (22.10.2026).

Dwie trasy: lista osób podobnych do tej (bez żadnej rekrutacji) i sprawdzenie
wybranych osób pod rekrutacje (umiejętności krytyczne, karta w rekrutacji).
Reguła i progi opisane w :mod:`app.services.similar_candidates`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateSearchAccess
from app.api.recruitment_access import ensure_job_read_access
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.candidate_rate_from import effective_rate
from app.services.my_people import active_process_counts
from app.services.similar_candidates import (
    PAGE_MAX,
    SimilarFilters,
    critical_check,
    find_similar,
    missing_labels,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

#: Najwięcej par osoba × rekrutacja w jednym sprawdzeniu.
CHECK_MAX_PAIRS = 200


class SimilarPersonOut(BaseModel):
    """Fakty osoby do porównania — te same pola dla źródła i podobnych."""

    id: int
    name: Optional[str] = None
    lastname: Optional[str] = None
    title: Optional[str] = None
    company: Optional[str] = None
    city: Optional[str] = None
    location: Optional[str] = None
    years_it_experience: Optional[int] = None
    competence_category: Optional[str] = None
    rate_hourly: Optional[float] = None
    rate_currency: Optional[str] = None
    availability_status: Optional[str] = None
    availability_date: Optional[date] = None
    active_processes: int = 0


class SimilarCandidateOut(SimilarPersonOut):
    score: float
    level: Literal["very", "similar", "partial"]
    shared_skills: list[str]
    only_source_skills: list[str]
    only_candidate_skills: list[str]
    #: Niepuste = „Możliwy duplikat” (``name`` / ``phone`` / ``linkedin`` /
    #: ``cv_file``) — reguła w ``services/similar_candidates.duplicate_signals``.
    duplicate_signals: list[str] = []


class SimilarCandidatesResponse(BaseModel):
    candidate_id: int
    #: ``no_vector`` — osoba nie ma jeszcze wektora CV; ``no_cv`` — ma wektor,
    #: ale bez CV i umiejętności nie ma z czym porównać; ``unavailable`` —
    #: wyszukiwarka nie odpowiedziała (to nie znaczy „nikogo nie ma”).
    status: Literal["ok", "no_vector", "no_cv", "unavailable"]
    total: int
    #: Osoba z profilu — druga kolumna porównania.
    source: SimilarPersonOut
    items: list[SimilarCandidateOut]


def _current_title_company(candidate: Candidate) -> tuple[Optional[str], Optional[str]]:
    """Ta sama kolejność co ``getCurrentTitle`` / ``getCurrentCompany`` na liście."""
    experience = candidate.experience if isinstance(candidate.experience, list) else []
    first = experience[0] if experience and isinstance(experience[0], dict) else {}
    title = candidate.linkedin_current_title or first.get("role") or None
    company = candidate.linkedin_current_company or first.get("company") or None
    return title, company


def _person_fields(candidate: Candidate, active_processes: int) -> dict:
    title, company = _current_title_company(candidate)
    amount, currency = effective_rate(candidate)
    availability = candidate.availability_status
    return {
        "id": candidate.id,
        "name": candidate.name,
        "lastname": candidate.lastname,
        "title": title,
        "company": company,
        "city": candidate.city,
        "location": candidate.location,
        "years_it_experience": candidate.years_it_experience,
        "competence_category": candidate.competence_category,
        "rate_hourly": float(amount) if amount is not None else None,
        "rate_currency": currency,
        "availability_status": getattr(availability, "value", availability),
        "availability_date": candidate.availability_date,
        "active_processes": active_processes,
    }


@router.get(
    "/candidates/{candidate_id}/similar",
    response_model=SimilarCandidatesResponse,
)
async def similar_candidates(
    candidate_id: int,
    current_user: CandidateSearchAccess,
    hide_not_looking: bool = True,
    without_process: bool = False,
    rate_max: Optional[Decimal] = Query(default=None, gt=0, le=10000),
    city: Optional[str] = Query(default=None, max_length=120),
    offset: int = Query(default=0, ge=0, le=1000),
    limit: int = Query(default=PAGE_MAX, ge=1, le=PAGE_MAX),
    db: AsyncSession = Depends(get_db),
) -> SimilarCandidatesResponse:
    """Osoby z podobnym CV i umiejętnościami — kolejność bez żadnej rekrutacji."""
    source = await db.get(Candidate, candidate_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej osoby.")
    result = await find_similar(
        db,
        source,
        SimilarFilters(
            hide_not_looking=hide_not_looking,
            without_process=without_process,
            rate_max=rate_max,
            city=city,
        ),
        offset=offset,
        limit=limit,
    )
    source_active = await active_process_counts(db, [source.id])
    return SimilarCandidatesResponse(
        candidate_id=candidate_id,
        status=result.status,
        total=result.total,
        source=SimilarPersonOut(
            **_person_fields(source, source_active.get(source.id, 0))
        ),
        items=[
            SimilarCandidateOut(
                **_person_fields(row.candidate, row.active_processes),
                score=row.score,
                level=row.level,
                shared_skills=list(row.overlap.shared),
                only_source_skills=list(row.overlap.only_source),
                only_candidate_skills=list(row.overlap.only_other),
                duplicate_signals=list(row.duplicate_signals),
            )
            for row in result.rows
        ],
    )


class SimilarCheckRequest(BaseModel):
    job_ids: list[int] = Field(..., min_length=1, max_length=25)
    candidate_ids: list[int] = Field(..., min_length=1, max_length=PAGE_MAX)

    @model_validator(mode="after")
    def _pairs_limit(self) -> "SimilarCheckRequest":
        if len(set(self.job_ids)) * len(set(self.candidate_ids)) > CHECK_MAX_PAIRS:
            raise ValueError(
                f"Najwyżej {CHECK_MAX_PAIRS} par osoba × rekrutacja naraz."
            )
        return self


class CriticalItemOut(BaseModel):
    label: str
    status: Literal["met", "missing", "unknown"]
    sources: list[str]


class InJobOut(BaseModel):
    label: str
    column: str
    closed: bool


class CandidateCheckOut(BaseModel):
    candidate_id: int
    critical: list[CriticalItemOut]
    missing: list[str]
    in_job: Optional[InJobOut] = None


class JobCheckOut(BaseModel):
    job_id: int
    critical_labels: list[str]
    candidates: list[CandidateCheckOut]


class SimilarCheckResponse(BaseModel):
    jobs: list[JobCheckOut]


@router.post(
    "/candidates/{candidate_id}/similar/check",
    response_model=SimilarCheckResponse,
)
async def similar_check(
    candidate_id: int,
    body: SimilarCheckRequest,
    current_user: CandidateSearchAccess,
    db: AsyncSession = Depends(get_db),
) -> SimilarCheckResponse:
    """Czy osoby spełniają krytyczne rekrutacji i czy już w niej są.

    Tylko odczyt — nic nie zapisuje. ``candidate_id`` to osoba z profilu,
    od której szukamy podobnych (adres zakładki); wynik dotyczy osób
    z ``candidate_ids``. Sprawdza rekrutacje, które patrzący może czytać
    (403 dla każdej innej).
    """
    from app.api.proposals_bulk import in_job_cards

    job_ids = list(dict.fromkeys(body.job_ids))
    candidate_ids = list(dict.fromkeys(body.candidate_ids))
    candidates = list(
        (await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))))
        .scalars()
        .all()
    )
    order = {cid: index for index, cid in enumerate(candidate_ids)}
    candidates.sort(key=lambda c: order[c.id])
    out: list[JobCheckOut] = []
    for job_id in job_ids:
        await ensure_job_read_access(db, current_user, job_id)
        job = await db.get(Job, job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
        checks = await critical_check(db, job, candidates)
        cards = await in_job_cards(db, job=job, candidates=candidates)
        labels = next(
            ([item.label for item in items] for items in checks.values() if items),
            [],
        )
        rows: list[CandidateCheckOut] = []
        for candidate in candidates:
            items = checks.get(candidate.id, [])
            card = cards.get(candidate.id)
            rows.append(
                CandidateCheckOut(
                    candidate_id=candidate.id,
                    critical=[
                        CriticalItemOut(
                            label=item.label,
                            status=item.status,
                            sources=list(item.sources),
                        )
                        for item in items
                    ],
                    missing=missing_labels(items),
                    in_job=(
                        InJobOut(
                            label=card.label,
                            column=card.column,
                            closed=card.closed is not None,
                        )
                        if card is not None
                        else None
                    ),
                )
            )
        out.append(JobCheckOut(job_id=job_id, critical_labels=labels, candidates=rows))
    return SimilarCheckResponse(jobs=out)
