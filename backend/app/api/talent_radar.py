"""POST /api/talent-radar/search — ad-hoc role → ranked candidates.

The recruiter-facing entry point for Talent Radar. Composition and the reasoning
behind its two constraints (mandatory client, no LLM call) live in
``app.services.talent_radar_search``; this module is transport only.


Deliberately WITHOUT ``from __future__ import annotations``. With PEP 563 on,
FastAPI sees the body model as a ForwardRef and resolves it as a *Query*
parameter, which blows up while building the OpenAPI schema. ``cv_match_preview``
carries the same warning in its own docstring — and I added the import here
anyway, so it is repeated where the next person will look.
"""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.api.deps import get_db
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.rate_limit import limiter
from app.schemas.matching_requirements import MatchingRequirements
from app.services.talent_radar_search import (
    normalize_skill_names,
    shape_radar_candidate,
    RadarQuery,
    TalentRadarError,
    search,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


class TalentRadarSearchRequest(BaseModel):
    """A role to look for, plus who it is for.

    `client_id` is required rather than optional: the eligibility filter checks
    the client blacklist, NDA, competitor conflicts and the hiring-manager veto
    against it. Making it optional would produce a list that silently skipped
    those checks — the defect fixed in `/ai-matches` on 2026-08-11.
    """

    client_id: int
    text: Optional[str] = Field(
        default=None,
        max_length=20_000,
        description="Treść zapytania / opisu roli, wklejona jak leci.",
    )
    champion_profile: Optional[dict[str, Any]] = Field(
        default=None,
        description="Profil Championa — używany zamiast lub obok treści.",
    )
    title: Optional[str] = Field(default=None, max_length=300)
    location: Optional[str] = Field(default=None, max_length=200)
    top_k: int = Field(default=20, ge=1, le=100)
    min_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)
    # Dealbreaker-switche. Budżet podaje rekruter wprost (radar nie ma
    # oferty) i SAMA JEGO OBECNOŚĆ aktywuje twardy sufit — bez marginesu
    # i bez osobnego przełącznika (decyzja produktowa 19.08). Nieznana
    # stawka/preferencja kandydata zawsze PRZECHODZI, a liczniki ukrytych
    # wracają w meta.hidden.
    budget_hourly_max: Optional[float] = Field(default=None, gt=0, le=2000)
    exclude_remote_only: bool = False
    # Rubryki 0278: dni w biurze / tydzień i miasto biura, podane WPROST przez
    # rekrutera (radar nie ma kolumn oferty). `onsite_days_per_week` uzbraja
    # dealbreakery dni/miasta TYLKO gdy > 0 — 0 jest legalną, „znaną" wartością
    # (praca wyłącznie zdalna) i nie aktywuje żadnego z dwóch nowych filtrów.
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    office_location: Optional[str] = Field(default=None, max_length=200)
    # Wymagania twarde/miękkie WPROST, zamiast wywodzonych regexem z prozy.
    # Wysyła je front po `parse-champion`; przy wklejonej treści zostają puste
    # i działa dotychczasowy fallback scoringu. Same nazwy, nie
    # `[{"name": ...}]` — kształt JSONB oferty składa dopiero
    # `build_ephemeral_job`, więc kontrakt API nie zależy od tego, jak
    # wygląda kolumna.
    #
    # `max_length` na liście = maksymalna LICZBA elementów (pydantic 2):
    # lista 10 tys. pozycji odbija się czytelnym 422 zamiast wejść w
    # arytmetykę warstwy skills, która zjechałaby wynik każdego kandydata
    # niemal do zera. Długość pojedynczej nazwy jest przycinana w
    # normalizatorze, nie odrzucana.
    must_skills: Optional[list[str]] = Field(default=None, max_length=50)
    nice_skills: Optional[list[str]] = Field(default=None, max_length=50)
    requirements_reviewed: bool = False
    matching_requirements: Optional[MatchingRequirements] = None


@router.post("/talent-radar/interpret")
async def interpret_requirements(
    payload: TalentRadarSearchRequest, _: CurrentUser
) -> dict:
    """Preview the same deterministic requirements used by the ranking."""
    from app.services.scoring_service import job_skill_requirements
    from app.services.talent_radar_search import build_ephemeral_job

    return job_skill_requirements(
        build_ephemeral_job(
            RadarQuery(
                client_id=payload.client_id,
                text=payload.text,
                title=payload.title,
                requirements_reviewed=payload.requirements_reviewed,
                champion_profile=payload.champion_profile,
                must_skills=normalize_skill_names(payload.must_skills),
                nice_skills=normalize_skill_names(payload.nice_skills),
                matching_requirements=payload.matching_requirements.model_dump()
                if payload.matching_requirements is not None
                else None,
            )
        )
    )


@router.post("/talent-radar/search")
@limiter.limit("20/minute")
async def talent_radar_search(
    request: Request,
    payload: TalentRadarSearchRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Rank the candidate base against a pasted request. Creates no Job.

    Dostęp: KAŻDA zalogowana rola (decyzja produktowa Artura 19.08 — radar
    i powiązane funkcje mają być dostępne dla wszystkich). Wyniki niosą
    tożsamość węższą niż profil (bez kontaktu i stawek), a LICZBY warstwy
    wynagrodzenia są ukrywane — to lista triage, nie profil; pełny profil
    kandydata pozostaje za bramkami modułu kandydatów. Sam `status` tej
    warstwy mówi prawdę o tym, czy weszła do wyniku (`_shape_result`).
    """
    try:
        result = await search(
            db,
            RadarQuery(
                client_id=payload.client_id,
                text=payload.text,
                champion_profile=payload.champion_profile,
                title=payload.title,
                location=payload.location,
                top_k=payload.top_k,
                min_score=payload.min_score,
                budget_hourly_max=payload.budget_hourly_max,
                exclude_remote_only=payload.exclude_remote_only,
                onsite_days_per_week=payload.onsite_days_per_week,
                office_location=payload.office_location,
                # Normalizacja TU, nie tylko po stronie `parse-champion`:
                # request jest sterowany przez klienta i wolno go POST-ować
                # wprost, z pominięciem parsowania profilu.
                must_skills=normalize_skill_names(payload.must_skills),
                nice_skills=normalize_skill_names(payload.nice_skills),
                matching_requirements=payload.matching_requirements.model_dump()
                if payload.matching_requirements is not None
                else None,
                requirements_reviewed=payload.requirements_reviewed,
            ),
        )
    except TalentRadarError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if result.degraded:
        # A degraded retrieval must not render as "nobody matches". The UI reads
        # `meta.degraded` and shows a failure notice instead of an empty state.
        logger.warning(
            "[talent-radar] degraded search for client=%s: %s",
            payload.client_id,
            result.reason,
        )

    return {
        "results": [
            _shape_result(
                breakdown,
                result.candidates_by_id.get(breakdown.candidate_id),
                result.eligibility_by_id.get(breakdown.candidate_id),
            )
            for breakdown in result.breakdowns
        ],
        "meta": result.as_meta(),
    }


def _shape_result(
    breakdown: Any, candidate: Any, eligibility: Optional[dict[str, Any]] = None
) -> dict[str, Any]:
    """A score plus who it belongs to, with the salary NUMBERS withheld.

    `/recommendations` blanks that layer unless the caller may see finance,
    because its points and reason are derived from the budget and would
    otherwise act as an oracle for it. The radar withholds them from EVERY
    role, for a reason of its own: this is a triage list that deliberately does
    not carry `expected_rate_hourly` (`shape_radar_candidate`), and the points
    are a linear function of the Champion rate the recruiter already knows —
    so publishing them would hand back the candidate rate to the złoty.

    What changes here is only what we SAY about that layer. It used to claim
    `not_applicable` unconditionally, which stopped being true once the
    Champion signals shipped: a profile with `rate_value` plus a candidate with
    an expected rate makes `_score_salary` score for real, and those points are
    inside `total`. Calling that "not applicable" meant the card actively
    denied the existence of the reason someone had dropped in the ranking.
    """

    payload = breakdown.as_dict()
    # `as_dict` publishes "scored" | "unknown" | "not_comparable"
    # (scoring_service, `LayerResult.status or "scored"`). Only "scored" means
    # the layer really entered `total`.
    scored = (payload.get("salary") or {}).get("status") == "scored"
    payload["salary"] = {
        "points": None,
        "max": None,
        "reason": None,
        # "redacted" is the sibling endpoint's word for "computed, not shown"
        # (`recommendations.py`). "not_applicable" stays for the honest case:
        # a pasted request with no Champion rate, or a candidate with no rate,
        # where the layer genuinely had nothing to judge.
        "status": "redacted" if scored else "not_applicable",
    }
    # `candidate` is None only if a row vanished between ranking and shaping.
    payload["candidate"] = shape_radar_candidate(candidate) if candidate else None
    # Badge of a client conflict / current employment (17.09.2026: warnings,
    # not blocks). ``None`` = no contraindication.
    payload["eligibility"] = eligibility
    return payload


@router.post("/talent-radar/parse-champion")
@limiter.limit("10/minute")
async def talent_radar_parse_champion(
    request: Request,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    from app.api.champion_intake import read_preview

    result = await read_preview(file, db)
    result["champion_profile"]["_source"] = "talent_radar_upload"
    return result
