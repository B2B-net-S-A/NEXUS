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
from app.services import champion_view
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
                # Normalizacja TU, nie tylko po stronie `parse-champion`:
                # request jest sterowany przez klienta i wolno go POST-ować
                # wprost, z pominięciem parsowania profilu.
                must_skills=normalize_skill_names(payload.must_skills),
                nice_skills=normalize_skill_names(payload.nice_skills),
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
    import anthropic

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

    # Świadomie POZA `try` niżej: ta funkcja nie dotyka dostawcy i połyka
    # własne błędy (zwraca None na nieczytelnym docx/pdf), więc objęcie jej
    # mapowaniem „dostawca padł" zamieniłoby zepsuty plik w komunikat
    # „spróbuj za chwilę" — czyli kazałoby czekać na coś, co samo nie minie.
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
    except anthropic.APIError as exc:
        # Awaria dostawcy to NIE jest zepsuty plik. `parse_champion_document`
        # zamienia na `ValueError` wyłącznie błędy parsowania ODPOWIEDZI —
        # przeciążenie (529), timeout i zerwane połączenie lecą wyżej i do
        # teraz kończyły się 500, a 500 z tej trasy nie ma nagłówków CORS,
        # więc w przeglądarce widać było „Network Error". Rekruter czytał to
        # jako „ten plik jest do niczego" i próbował kolejnych zamiast
        # poczekać minutę. 503 z komunikatem po polsku mówi, co się stało, i
        # jest odróżnialne od 422 (dokument), i od 413 (rozmiar).
        logger.warning("[talent-radar] parse-champion — dostawca AI padł: %s", exc)
        raise HTTPException(
            status_code=503,
            detail="Model AI chwilowo niedostępny — spróbuj za chwilę.",
        ) from exc
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

    # Listy WRACAJĄ do klienta, nie tylko ich długość. Do teraz endpoint je
    # parsował, pokazywał „8 must · 5 nice" i WYRZUCAŁ, a ranking liczył z
    # wymagań wywodzonych regexem z prozy — plakietka obiecywała wiedzę,
    # której scoring nigdy nie dostał. `build_champion_dict` ich NIE kopiuje
    # i nie będzie: jego wyjście to 1:1 kształt `jobs.champion_profile`
    # utrwalany przez import, więc dokładanie tam radarowych kluczy zmieniłoby
    # JSONB zapisywany w całym systemie.
    #
    # UWAGA: przy `TALENT_RADAR_STRUCTURED_SKILLS_ENABLED=false` (default)
    # backend te listy PRZYJMIE i zignoruje — łańcuch jest kompletny, ale
    # ranking dalej wywodzi wymagania z prozy. Plakietka pozostaje więc
    # obietnicą na wyrost do czasu flipu; odpowiedź świadomie NIE niesie
    # pozycji flagi, żeby kształt tej odpowiedzi nie zależał od konfiguracji.
    _stack = parsed.get("stack") if isinstance(parsed.get("stack"), dict) else {}
    musts = normalize_skill_names(_stack.get("must") or parsed.get("must_skills"))
    nices = normalize_skill_names(_stack.get("nice") or parsed.get("nice_skills"))
    _summary_basics = champion_view.basics(profile)
    return {
        "champion_profile": profile,
        "must_skills": musts,
        "nice_skills": nices,
        "summary": {
            "role_name": parsed.get("role_name"),
            # Liczniki liczą to, co POJEDZIE do rankingu — wpis bez `name`
            # odpada w normalizacji, więc licznik z surowej listy pokazywałby
            # więcej wymagań, niż system faktycznie zna.
            "must_count": len(musts),
            "nice_count": len(nices),
            # Przez `champion_view.basics`, bo prompt v4 zwraca te trzy fakty
            # w sekcji 1, a v3 kładł je płasko. Odczyt wprost pokazywałby
            # w podsumowaniu „—" przy stawce, którą model właśnie odczytał.
            "rate_value": _summary_basics.get("rate_value"),
            "location": _summary_basics.get("candidate_location_pref")
            or parsed.get("location"),
            "work_mode": _summary_basics.get("work_mode"),
        },
    }
