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
from app.core.rate_limit import limiter
from app.services.talent_radar_search import (
    shape_radar_candidate,
    RadarQuery,
    TalentRadarError,
    search,
)

logger = logging.getLogger(__name__)

router = APIRouter()


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
    tożsamość węższą niż profil (bez kontaktu i stawek), a warstwa
    wynagrodzenia jest wygaszana — to lista triage, nie profil; pełny profil
    kandydata pozostaje za bramkami modułu kandydatów.
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
                breakdown, result.candidates_by_id.get(breakdown.candidate_id)
            )
            for breakdown in result.breakdowns
        ],
        "meta": result.as_meta(),
    }


def _shape_result(breakdown: Any, candidate: Any) -> dict[str, Any]:
    """A score plus who it belongs to, with the salary layer redacted.

    `/recommendations` blanks that layer unless the caller may see finance,
    because its points and reason are derived from the job budget and would
    otherwise act as an oracle for it. Here the layer is *structurally*
    unscored — an ad-hoc radar query carries no budget at all, so
    `_score_salary` short-circuits — but returning it raw would leave the
    contract one refactor away from leaking, and would show the recruiter a
    zero that means "not applicable" rather than "bad fit". Blanking it says
    the true thing and matches the sibling endpoint.
    """

    payload = breakdown.as_dict()
    payload["salary"] = {
        "points": None,
        "max": None,
        "reason": None,
        "status": "not_applicable",
    }
    # `candidate` is None only if a row vanished between ranking and shaping.
    payload["candidate"] = shape_radar_candidate(candidate) if candidate else None
    return payload


@router.post("/talent-radar/parse-champion")
@limiter.limit("10/minute")
async def talent_radar_parse_champion(
    request: Request,
    current_user: CurrentUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Plik profilu Championa (docx/pdf) → sparsowany profil dla radaru.

    Rekruter dostaje profil od zespołu jako DOKUMENT — wklejanie go ręcznie
    do pola tekstowego gubi strukturę (stawka, must/nice, screening). Ten
    endpoint parsuje plik tym samym promptem v3 co import sierpniowy i zwraca
    kształt zgodny z `TalentRadarSearchRequest.champion_profile`, więc wynik
    idzie prosto w wyszukiwanie — bez zakładania rekrutacji i BEZ zapisu
    czegokolwiek do bazy (radar pozostaje bezstanowy).

    Kwota: ten sam kubełek co ingest (`champion_profile_parse`).
    """
    from app.models.ai_feature import AIFeatureKey
    from app.services.ai_quota import AIQuotaExceeded, ai_feature
    from app.services.champion_profile_ingest import (
        build_champion_dict,
        extract_document_text,
        oversize_precheck,
        parse_champion_document,
        validate_upload,
    )

    # Odbij za duży plik PRZED wczytaniem do pamięci (Content-Length), nie po.
    too_big = oversize_precheck(getattr(file, "size", None))
    if too_big:
        raise HTTPException(status_code=413, detail=too_big)
    content = await file.read()
    error = validate_upload(file.filename or "", len(content))
    if error:
        raise HTTPException(status_code=422, detail=error)

    text = extract_document_text(content, file.filename or "")
    if not text or len(text) < 200:
        raise HTTPException(
            status_code=422,
            detail="Nie udało się odczytać tekstu z pliku (skan bez OCR albo pusty dokument).",
        )

    try:
        async with ai_feature(db, AIFeatureKey.champion_profile_parse):
            parsed = await parse_champion_document(text)
    except AIQuotaExceeded as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Nie udało się sparsować profilu: {exc}",
        ) from exc

    # file_id=None jako sentinel: to upload bez rekrutacji, nie plik Traffita
    # (build_champion_dict tworzy _source, który i tak nadpisujemy — sentinel
    # unika mylącego pośredniego "traffit_recruitment_file:0").
    profile = build_champion_dict(parsed, file_id=None)
    profile["_source"] = "talent_radar_upload"

    musts = parsed.get("must_skills") or []
    nices = parsed.get("nice_skills") or []
    return {
        "champion_profile": profile,
        "summary": {
            "role_name": parsed.get("role_name"),
            "must_count": len(musts),
            "nice_count": len(nices),
            "rate_value": parsed.get("rate_value"),
            "location": parsed.get("location"),
            "work_mode": parsed.get("work_mode"),
        },
    }
