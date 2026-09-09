"""
Phase 2 recommendations engine endpoints.

Extends the Phase 1 `/api/jobs/{id}/ai-matches` with a richer `/recommendations`
endpoint that returns an explainable ScoreBreakdown per candidate, and adds a
reverse `/api/candidates/{id}/recommendations` for candidate→jobs direction.

Also exposes `POST /api/jobs/{id}/refresh-criteria` (AI-generated must/nice
skills via Ollama) and `POST /api/jobs/{id}/recompute-scores` (batch rescoring).
"""

from __future__ import annotations

import logging
import re
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.candidate_access import (
    CandidateWriteAccess,
    require_candidate_read,
    require_candidate_roles,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.services.candidate_stage_cv_service import (
    create_original_cv_snapshot,
)
from app.services.candidate_contact_hooks import maybe_ensure_contact_opportunity
from app.core.rate_limit import limiter
from app.models.user import User, UserRole
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_priority import PriorityChannel
from app.services.candidate_job_eligibility import (
    ConflictInput,
    EligibilityInput,
    EligibilityReason,
    evaluate_eligibility,
    extract_excluded_client_ids,
)
from app.services.pipeline_eligibility import filter_eligible_candidates
from app.services.access_scope import (
    apply_delivery_lead_client_scope,
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
)
from app.services.hiring_manager_verdicts import load_manager_rejections
from app.services.recruitment_process_commands import open_process
from app.services.embedding_service import (
    SemanticSearchUnavailable,
    embed_job,
    search_jobs_semantic,
)
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    WeightProfile,
    rank_jobs_for_candidate,
    resolve_active_profile,
)
from app.services.location_utils import location_tokens
from app.services.similar_job_candidates import (
    fetch_historical_boost_map,
    fetch_historical_candidates,
)
from app.schemas.similar_job_candidates import (
    CandidatesFromSimilarOut,
    HistoricalCandidateOut,
    HistoricalCandidatesMeta,
    HistoricalSourceOut,
    SimilarJobOut,
)
from app.services.canonical_text import build_job_query_variants
from app.services.retrieval_pool import retrieve_candidate_pool
from app.services.section_permissions import SectionAccess

logger = logging.getLogger(__name__)

router = APIRouter()

_ADMIN_OR_DELIVERY_LEAD_CANDIDATE_READ = require_candidate_roles(
    UserRole.admin,
    UserRole.delivery_lead,
)
_ADMIN_OR_DELIVERY_LEAD_CANDIDATE_WRITE = require_candidate_roles(
    UserRole.admin,
    UserRole.delivery_lead,
    required_access=SectionAccess.write,
)


def _score_breakdown_payload(
    breakdown,
    *,
    include_finance: bool = False,
) -> dict:
    """Return an explainable score without leaking its salary-derived layer."""

    payload = breakdown.as_dict()
    if not include_finance:
        # Keep the response contract stable while preventing the points/reason
        # from becoming an oracle for a hidden job budget.
        payload["salary"] = {
            "points": None,
            "max": None,
            "reason": None,
            "status": "redacted",
        }
    return payload


def _shape_recommended_job(job: Job, *, include_finance: bool = False) -> dict:
    """Candidate→job response projection with capability-aware budget fields."""

    return {
        "id": job.id,
        "title": job.title,
        "client_id": job.client_id,
        "location": job.location,
        "salary_min": job.salary_min if include_finance else None,
        "salary_max": job.salary_max if include_finance else None,
        "remote_policy": (job.remote_policy.value if job.remote_policy else None),
        "status": job.status.value if job.status else None,
        "priority": job.priority.value if job.priority else None,
        "seniority": job.seniority.value if job.seniority else None,
        "industry": job.industry,
        "deadline": job.deadline.isoformat() if job.deadline else None,
    }


def _assert_salary_filter_access(
    user: User,
    *,
    salary_min: int | None,
    salary_max: int | None,
) -> None:
    """Reject hidden-budget probing instead of silently applying the filter."""

    if (salary_min is not None or salary_max is not None) and not user_has_capability(
        user, AnalyticsCapability.VIEW_FINANCE
    ):
        raise HTTPException(
            status_code=403,
            detail="Salary filters require view_finance capability",
        )


# ── Job → candidates (explainable) ──────────────────────────────────────────


@router.get("/jobs/{job_id}/recommendations")
@limiter.limit("20/minute")
async def recommend_candidates_for_job(
    request: Request,
    job_id: int,
    top_k: int = Query(
        200, ge=1, le=200, description="Hard cap on results (payload safety bound)."
    ),
    min_score: float | None = Query(
        None,
        ge=0.0,
        le=100.0,
        description=(
            "Minimum hybrid score (0-100) a candidate must reach to be shown. "
            "Defaults to settings.RECOMMENDATION_MIN_SCORE. Lower = show more."
        ),
    ),
    include_breakdown: bool = Query(True),
    exclude_in_pipeline: bool = Query(
        True, description="Skip candidates already added to this job's pipeline."
    ),
    profile_id: Optional[int] = Query(
        None,
        description=(
            "Optional scoring weight profile id (Phase D1). If omitted, falls back "
            "to user → client → global → built-in default."
        ),
    ),
    location: str | None = Query(
        None,
        max_length=120,
        description=(
            "Restrict results to candidates whose location matches this place "
            "(city/region, substring-tolerant, blob-aware). Omitted means no "
            "hard location filter; the request's location remains a fit signal."
        ),
    ),
    location_source: str = Query(
        "all",
        pattern="^(all|cv|notes)$",
        description=(
            "Źródło lokalizacji kandydata dla filtra `location`: 'cv' "
            "(kolumny city/location), 'notes' (fakty z rozmów: "
            "preferences.locations + kierunki relokacji), 'all' (unia)."
        ),
    ),
    exclude_over_budget: bool = Query(
        True,
        description=(
            "Dealbreaker (domyślnie WŁĄCZONY — decyzja produktowa 19.08): "
            "znany budżet oferty (jawne pole lub stawka Championa) ukrywa "
            "kandydatów, których ZNANA stawka PLN/h jest ściśle powyżej "
            "niego. Nieznana stawka zawsze przechodzi; ustaw false, żeby "
            "pokazać też przekraczających."
        ),
    ),
    exclude_remote_only: Optional[bool] = Query(
        None,
        description=(
            "Dealbreaker: ukryj kandydatów z potwierdzonym w rozmowach "
            "'wyłącznie zdalnie' (preferences.remote_only). Domyślnie AUTO "
            "(0278): pominięte — aktywuje się samo, gdy oferta wymaga biura "
            "(kolumna/Champion/dni w biurze > 0). Jawne `true`/`false` zawsze "
            "wygrywa nad AUTO. Nieznana preferencja zawsze przechodzi."
        ),
    ),
    exclude_missing_must: Optional[bool] = Query(
        None,
        description=(
            "Pominięte: stosuj zapisaną politykę brakujących dowodów, domyślnie "
            "do weryfikacji. Jawne true/false nadpisuje ją dla tego zapytania."
        ),
    ),
    exclude_office_days_exceeded: bool = Query(
        True,
        description=(
            "Dealbreaker (0278): ukryj kandydatów, których deklarowany limit "
            "dni w biurze jest niższy niż wymóg oferty. Działa tylko gdy "
            "oferta ma jawną liczbę dni; nieznana deklaracja przechodzi."
        ),
    ),
    exclude_office_city_mismatch: bool = Query(
        True,
        description=(
            "Dealbreaker (0278): ukryj kandydatów, których znane miasta biura "
            "nie pokrywają się z miastem oferty. Działa tylko gdy oferta "
            "wymaga dni w biurze i ma jawne miasto."
        ),
    ),
    current_user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
):
    """
    Top-K ranking of candidates for a job using hybrid scoring
    (semantic 40 + skills 30 + salary 15 + location 10 + availability 5 − penalties).

    Transport-only wrapper: parses/validates query params and delegates to
    ``_recommend_candidates_core`` so in-process callers (``recompute_scores``)
    never touch FastAPI ``Query(...)`` sentinels or the slowapi wrapper
    (M3-API-01).
    """
    return await _recommend_candidates_core(
        job_id,
        current_user=current_user,
        db=db,
        top_k=top_k,
        min_score=min_score,
        include_breakdown=include_breakdown,
        exclude_in_pipeline=exclude_in_pipeline,
        profile_id=profile_id,
        location=location,
        location_source=location_source,
        exclude_over_budget=exclude_over_budget,
        exclude_remote_only=exclude_remote_only,
        exclude_missing_must=exclude_missing_must,
        exclude_office_days_exceeded=exclude_office_days_exceeded,
        exclude_office_city_mismatch=exclude_office_city_mismatch,
    )


def _annotate_historical_context(breakdowns: list, boost_map: dict[int, int]) -> None:
    """History describes process experience; it cannot change base fit or order."""
    for b in breakdowns:
        b.historical_boost = 0.0
        b.historical_sources_count = max(0, boost_map.get(b.candidate_id, 0))
    breakdowns.sort(key=lambda b: (-b.total, b.candidate_id))


async def _recommend_candidates_core(
    job_id: int,
    *,
    current_user: User,
    db: AsyncSession,
    top_k: int = 200,
    min_score: float | None = None,
    include_breakdown: bool = True,
    exclude_in_pipeline: bool = True,
    profile_id: Optional[int] = None,
    location: str | None = None,
    location_source: str = "all",
    exclude_over_budget: bool = True,
    exclude_remote_only: Optional[bool] = None,
    exclude_missing_must: bool | None = None,
    exclude_office_days_exceeded: bool = True,
    exclude_office_city_mismatch: bool = True,
) -> dict:
    """Application-service core of job→candidates recommendations.

    Plain async function (no FastAPI transport objects) — callable from the
    route above and from ``recompute_scores`` without a ``Request``.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    assert_delivery_lead_client_visible(
        job.client_id,
        await resolve_delivery_lead_client_ids(current_user, db),
    )

    # ── Location filter (post-scoring; mirrors legacy /ai-matches PR #424) ────
    # Only an explicit query filter is hard; the job location remains a fit input.
    requested_location = (location or "").strip()
    requested_tokens = location_tokens(requested_location)
    location_active = bool(requested_tokens)

    # Phase D1: resolve active weight profile for this request.
    profile: WeightProfile = DEFAULT_PROFILE
    if profile_id is not None:
        from app.models.scoring_weight_profile import ScoringWeightProfile

        row = await db.scalar(
            select(ScoringWeightProfile).where(ScoringWeightProfile.id == profile_id)
        )
        if row:
            profile = WeightProfile.from_record(row)
    else:
        profile = await resolve_active_profile(
            db, user_id=current_user.id, client_id=job.client_id
        )

    from app.services.canonical_fit import score_candidates
    from app.services.request_matching_context import build_request_context
    from app.services.search_telemetry import SearchTelemetry

    fit_context = build_request_context(job, profile)
    query_text = fit_context.query_text

    # Pull a wider candidate pool from Qdrant, then re-rank with rules. When a
    # location filter is active, widen retrieval so the sparse located subset
    # (~17% of candidates have any location) isn't starved by the top-200
    # semantic cut — only the matched subset is actually scored (pre-filter
    # below), so the extra retrieval doesn't multiply scoring cost.
    # Pool size is independent of `top_k` on purpose. The old `top_k * 4`
    # heuristic tied "how many we retrieve" to "how many we show", so a request
    # for the top 20 retrieved 80 and capped its own recall ceiling at ~4%
    # (measured 2026-08-10: ceiling is 1.8% at pool 20, 13.6% at 200, 32.6% at
    # 1000). `top_k` still caps what comes back — it just no longer decides what
    # scoring is allowed to see.
    pool_size = settings.MATCH_POOL_SIZE
    if location_active:
        pool_size = max(pool_size, settings.RECOMMENDATION_LOCATION_POOL_SIZE)
    # C12: noga BM25 hybrydy MUSI dostać terminy, nie `query_text`. Dokument
    # w roli tsquery to koniunkcja setek leksemów, czyli zero trafień zawsze —
    # i to zero jest niewidoczne, bo fuzja RRF z pustą listą zwraca czysty
    # porządek wektora. Bez tego argumentu hybryda kosztuje, a nie wnosi.
    from app.services.hybrid_search import build_job_bm25_query, build_job_must_groups

    hits = await retrieve_candidate_pool(
        db,
        query_text,
        top_k=pool_size,
        query_variants=build_job_query_variants(job, query_text),
        bm25_query=build_job_bm25_query(job),
        # 0278: rodziny must-have dla strategii SQL-first — no-op, dopóki
        # `STRUCTURED_POOL_ENABLED` jest wyłączona.
        must_groups=build_job_must_groups(job),
    )
    candidate_ids = list(dict.fromkeys(h["candidate_id"] for h in hits))

    # Retrieval completeness is separate from the exact fit measurements.
    semantic_unknown_ids = {
        h["candidate_id"] for h in hits if h.get("semantic_unknown")
    }
    semantic_degraded = not candidate_ids or bool(semantic_unknown_ids)

    # Pusty wynik od startu: _meta() bywa wołane we wczesnych returnach
    # (degradacja semantyki, pusty filtr lokalizacji) ZANIM switche zadziałają.
    from app.services.dealbreaker_filters import DealbreakerResult

    dealbreakers = DealbreakerResult()

    def _meta() -> dict:
        # Retrieval or exact measurement was incomplete. Individual unknown
        # scores remain null; a populated candidate pool is not proof of health.
        return {
            "mode": "degraded_semantic" if semantic_degraded else "dense",
            "degraded": semantic_degraded,
            "reason": "semantic_unavailable" if semantic_degraded else None,
            "hidden": dealbreakers.hidden_meta(),
        }

    # Fallback when Qdrant is empty — widen to all active candidates (cap 200)
    if not candidate_ids:
        fallback = await db.execute(
            select(Candidate.id)
            .where(Candidate.status != CandidateStatus.blacklisted)
            # Bez `ORDER BY` „pierwsze 200" to arbitralny wycinek, inny przy
            # każdym wywołaniu — ten sam rekruter dwa razy z rzędu dostawał
            # inną pulę i nie miał jak tego zauważyć. Malejąco po id: najnowsi
            # kandydaci są najbardziej aktualni.
            .order_by(Candidate.id.desc())
            .limit(settings.MATCH_POOL_SIZE)
        )
        candidate_ids = [c for (c,) in fallback.all()]

    if exclude_in_pipeline and candidate_ids:
        in_pipeline = await db.execute(
            select(CandidateStage.candidate_id)
            .where(
                CandidateStage.job_id == job_id,
                CandidateStage.candidate_id.in_(candidate_ids),
            )
            .distinct()
        )
        already = {cid for (cid,) in in_pipeline.all()}
        candidate_ids = [cid for cid in candidate_ids if cid not in already]

    if not candidate_ids:
        return {
            "job_id": job_id,
            "job_title": job.title,
            "search_type": "hybrid",
            "location_filter": requested_location if location_active else None,
            "matches": [],
            "meta": _meta(),
        }

    cand_res = await db.execute(
        select(Candidate).where(Candidate.id.in_(candidate_ids))
    )
    candidates = list(cand_res.scalars().all())

    # Location filter: drop candidates whose location doesn't match BEFORE
    # scoring, so only the matched subset bears the (cache-first) scoring cost.
    # A candidate with no parseable location is excluded under an active filter
    # (standard search semantics, mirroring manual-search `location_cities`).
    if location_active:
        from app.services.location_utils import (
            candidate_location_tokens,
            tokens_overlap,
        )

        candidates = [
            c
            for c in candidates
            if tokens_overlap(
                requested_tokens, candidate_location_tokens(c, location_source)
            )
        ]
        if not candidates:
            return {
                "job_id": job_id,
                "job_title": job.title,
                "search_type": "hybrid",
                "location_filter": requested_location,
                "matches": [],
                "meta": _meta(),
            }

    # P0-A: hard eligibility prefilter BEFORE scoring — a candidate the recruiter
    # could not assign (global blacklist / active client blacklist·NDA·competitor
    # / a standing hiring-manager veto) must never surface as a recommendation.
    # Soft signals (current employment, candidate-excluded client) stay as
    # warnings, exactly as on the assign ingress, so "recommended ⟹ assignable".
    from datetime import datetime, timezone

    candidates = await filter_eligible_candidates(
        db, job=job, candidates=candidates, now=datetime.now(timezone.utc)
    )

    # Dealbreaker-switche: twardy sufit budżetu działa Z AUTOMATU (decyzja
    # produktowa 19.08) — znany budżet oferty ukrywa znane stawki powyżej.
    # Nieznany przechodzi; liczniki idą do meta.hidden, żeby ukrywanie nigdy
    # nie było ciche (reguła „awaria ≠ pustka"). Rubryki 0278 (must-have / dni
    # w biurze / miasto) rozwiązane RAZ przez `dealbreaker_inputs_for_job` —
    # ta sama funkcja, której używa `/ai-matches` i snapshot handoffu, więc
    # wszystkie powierzchnie liczą te trzy rubryki identycznie.
    from app.services.dealbreaker_filters import (
        apply_dealbreakers,
    )
    from app.services.requirement_contract import search_dealbreaker_inputs

    dealbreakers = apply_dealbreakers(
        candidates,
        inputs=search_dealbreaker_inputs(
            job, exclude_missing_must=exclude_missing_must
        ),
        exclude_over_budget=exclude_over_budget,
        exclude_remote_only=exclude_remote_only,
        exclude_missing_must=exclude_missing_must is not False,
        exclude_office_days_exceeded=exclude_office_days_exceeded,
        exclude_office_city_mismatch=exclude_office_city_mismatch,
    )
    candidates = dealbreakers.kept

    if not candidates:
        return {
            "job_id": job_id,
            "job_title": job.title,
            "search_type": "hybrid",
            "location_filter": requested_location if location_active else None,
            "matches": [],
            "meta": _meta(),
        }

    telemetry = SearchTelemetry()
    telemetry.begin_attempt()
    # The preceding legacy retrieval can also call providers/rerankers. Until
    # it shares this accounting scope, never label the fit subtotal a full cost.
    telemetry.data["scope"] = "canonical_fit_only"
    telemetry.data["accounting_complete"] = False
    with telemetry.activate():
        fits = await score_candidates(db, fit_context, candidates)
    fits_by_id = {fit.breakdown.candidate_id: fit for fit in fits}
    breakdowns = [fit.breakdown for fit in fits]
    semantic_degraded = semantic_degraded or any(fit.fit_score is None for fit in fits)

    # Process history is fresh context, separate from fit and its threshold.
    try:
        boost_map = await fetch_historical_boost_map(db, job_id)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("historical_boost lookup failed for job=%s: %s", job_id, e)
        boost_map = {}
    _annotate_historical_context(breakdowns, boost_map)

    # Show ALL candidates that fit (score >= threshold), not a fixed top-K.
    # `top_k` now acts purely as a payload safety cap. The hybrid composite is a
    # ranking signal with a low absolute range, so the default threshold is low
    # (see settings.RECOMMENDATION_MIN_SCORE for calibration notes).
    threshold = (
        min_score if min_score is not None else settings.RECOMMENDATION_MIN_SCORE
    )
    # Preserve unknown measurements for review, after all measured fits.
    breakdowns = [
        fit.breakdown
        for fit in fits
        if fit.fit_score is None or fit.fit_score >= threshold
    ][:top_k]

    matches = []
    for b in breakdowns:
        c = next((x for x in candidates if x.id == b.candidate_id), None)
        if not c:
            continue
        match = {
            "candidate": {
                "id": c.id,
                "name": c.name,
                "lastname": c.lastname,
                "email": c.email,
                "phone": c.phone,
                "location": c.location,
                "status": c.status.value if c.status else None,
                "competence_category": c.competence_category,
                "years_it_experience": c.years_it_experience,
                "champion": c.champion,
                "avatar_url": c.avatar_url,
                "tags": c.tags,
                "skills": c.skills,
                "ai_summary": c.ai_summary,
            },
            "total_score": fits_by_id[b.candidate_id].fit_score,
            "measurement": fits_by_id[b.candidate_id].measurement,
        }
        if include_breakdown and fits_by_id[b.candidate_id].fit_score is not None:
            match["breakdown"] = _score_breakdown_payload(
                b,
                include_finance=user_has_capability(
                    current_user, AnalyticsCapability.VIEW_FINANCE
                ),
            )
        matches.append(match)

    return {
        "job_id": job_id,
        "job_title": job.title,
        "search_type": "hybrid",
        "request_fingerprint": fit_context.fingerprint,
        "versions": fit_context.versions,
        "metrics": telemetry.snapshot(),
        "min_score": round(threshold, 1),
        "profile": {"id": profile.id, "name": profile.name},
        "location_filter": requested_location if location_active else None,
        "matches": matches,
        "meta": _meta(),
    }


# ── Pipeline match scores (kanban badges) ────────────────────────────────────


@router.get("/jobs/{job_id}/pipeline-scores")
@limiter.limit("30/minute")
async def pipeline_match_scores(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
):
    """Canonical base fit for every current pipeline member, in bounded batches.

    Process membership is returned independently of measurement availability.
    The old composite score cache is deliberately incompatible: its document,
    weights and screening component differ from the shared search contract.
    """
    from app.api.candidate_search import _authorized_job
    from app.services.pipeline_base_fit import pipeline_base_fit

    job = await _authorized_job(db, current_user, job_id)
    profile = await resolve_active_profile(
        db, user_id=current_user.id, client_id=job.client_id
    )
    return await pipeline_base_fit(db, job, profile)


# ── Historical candidates from similar jobs (Phase 14) ───────────────────────


def _derive_availability(candidate: Candidate) -> str:
    """Map candidate availability state into a tri-value badge label."""
    status = getattr(candidate, "availability_status", None)
    if status == AvailabilityStatus.actively_looking:
        return "available"
    if status == AvailabilityStatus.open_to_offers:
        return "available"
    if status == AvailabilityStatus.not_looking:
        return "busy"
    return "unknown"


@router.get(
    "/jobs/{job_id}/candidates-from-similar",
    response_model=CandidatesFromSimilarOut,
)
@limiter.limit("20/minute")
async def candidates_from_similar_jobs(
    request: Request,
    job_id: int,
    tier: str = Query(
        "primary",
        description=(
            "`primary` uses only Tier A (cosine >= 0.70) similar jobs. "
            "`extended` includes Tier B (>= 0.55). `all` is a synonym for "
            "extended. Tier A is auto-promoted to extended when it returns "
            "fewer than 5 candidates."
        ),
    ),
    limit: int = Query(20, ge=1, le=100),
    include_negative: bool = Query(
        True,
        description=(
            "When false, candidates with only rejected/withdrawn history on "
            "similar jobs are dropped. When true, they surface with a warning "
            "badge (`negative_signal=True`)."
        ),
    ),
    top_k_similar: int = Query(20, ge=1, le=50),
    current_user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
) -> CandidatesFromSimilarOut:
    """Return candidates who were active in semantically similar past jobs.

    Implements the "pierwszy ogień" pattern: when a new job comes in, avoid
    starting from zero by surfacing the people who were already vetted on
    comparable roles. Every candidate carries the list of source jobs
    (up to 5 most recent) so the recruiter can judge whether the historical
    fit still applies.
    """
    if tier not in {"primary", "extended", "all"}:
        raise HTTPException(status_code=400, detail="tier must be primary|extended|all")

    from datetime import datetime, timezone

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    ranked, similar_refs, tier_used = await fetch_historical_candidates(
        db,
        job_id=job_id,
        tier=tier,  # type: ignore[arg-type]
        limit=limit,
        include_negative=include_negative,
        top_k_similar=top_k_similar,
        target_client_id=job.client_id,
    )

    total_sources = sum(len(c.sources) for c in ranked)
    tier_a_count = sum(1 for r in similar_refs if r.tier == "A")
    tier_b_count = sum(1 for r in similar_refs if r.tier == "B")

    if not similar_refs:
        # `degraded` z `fetch_similar_jobs` znaczy „Qdrant nie odpowiedział",
        # a nie „nie ma podobnych ofert" — i musi PRZEJŚĆ przez ten wczesny
        # return, a nie zostać nadpisane na „empty". Degradacja z definicji
        # daje pustą listę refów, więc to jedyne miejsce, którym może wyjść:
        # nadpisanie zamykało ją tu na głucho i rekruter widział podczas awarii
        # komunikat o BRAKU historii. Ta sama klasa co #408, odtworzona obok
        # własnej naprawy.
        degraded = tier_used == "degraded"
        return CandidatesFromSimilarOut(
            job_id=job_id,
            tier_used="degraded" if degraded else "empty",
            similar_jobs=[],
            candidates=[],
            meta=HistoricalCandidatesMeta(
                tier_a_count=0,
                tier_b_count=0,
                total_sources=0,
                reason_if_empty=(
                    "similar_jobs_unavailable" if degraded else "no_similar_jobs_found"
                ),
            ),
        )

    reason_empty: Optional[str] = None
    if not ranked:
        reason_empty = "no_pipeline_history_on_similar_jobs"

    # Hydrate candidate records (name, avatar, availability) in a single query.
    cand_ids = [c.candidate_id for c in ranked]
    cand_rows: list[Candidate] = []
    if cand_ids:
        cand_res = await db.execute(select(Candidate).where(Candidate.id.in_(cand_ids)))
        cand_rows = list(cand_res.scalars().all())

    # P0-A: ta sekcja jest na przeciek SZCZEGÓLNIE narażona, nie mniej.
    # „Kandydaci z podobnych projektów" z definicji celują w ludzi, którzy BYLI
    # już rozważani u tego klienta — a to dokładnie ta populacja, w której
    # siedzą aktywne blacklisty klienta, NDA i weta hiring managera. Serwis
    # (`similar_job_candidates._rank_candidates_from_similar`) filtruje wyłącznie
    # blacklistę GLOBALNĄ i nie ma dostępu do `job`; endpoint ma komplet wejść
    # bramki, więc bramka stoi tutaj.
    #
    # Licznik liczy się po ZHYDRATOWANYCH wierszach, nie po `cand_ids`: kandydat,
    # który zniknął z bazy w międzyczasie, nie jest „ukryty" — mówienie o nim
    # „zablokowany dla tego klienta" byłoby nieprawdą w drugą stronę.
    before_gate = len(cand_rows)
    cand_rows = await filter_eligible_candidates(
        db, job=job, candidates=cand_rows, now=datetime.now(timezone.utc)
    )
    hidden_ineligible = before_gate - len(cand_rows)
    cand_by_id = {c.id: c for c in cand_rows}

    def _availability_sort_key(c: HistoricalCandidateOut) -> tuple[int, float]:
        # 0 = available (show first), 1 = unknown, 2 = busy — within each
        # bucket keep historical_score desc.
        bucket = {"available": 0, "unknown": 1, "busy": 2}.get(
            c.current_availability, 1
        )
        return (bucket, -c.historical_score)

    out_candidates: list[HistoricalCandidateOut] = []
    for hc in ranked:
        c = cand_by_id.get(hc.candidate_id)
        if c is None:
            continue
        out_candidates.append(
            HistoricalCandidateOut(
                candidate_id=hc.candidate_id,
                name=c.name,
                lastname=c.lastname,
                avatar_url=c.avatar_url,
                competence_category=c.competence_category,
                historical_score=hc.historical_score,
                tier=hc.tier,
                negative_signal=hc.negative_signal,
                recommended_count=len(hc.sources),
                sources=[
                    HistoricalSourceOut(
                        job_id=s.job_id,
                        job_title=s.job_title,
                        stage=s.stage.value,
                        similarity=s.similarity,
                        months_ago=s.months_ago,
                        moved_at=s.moved_at,
                        stage_weight=s.stage_weight,
                        contribution=s.contribution,
                        client_id=s.client_id,
                    )
                    for s in hc.sources
                ],
                current_availability=_derive_availability(c),  # type: ignore[arg-type]
                current_status=c.status.value if c.status else None,
                same_client=hc.same_client,
                rejected_by_same_client=hc.rejected_by_same_client,
            )
        )

    out_candidates.sort(key=_availability_sort_key)

    # Pustka SKORELOWANA z przyczyną. Reguła z repo mówi, że „ukryto N" bez
    # wskazania jest bezużyteczne — ale pustka bez wyjaśnienia jest gorsza,
    # a tutaj przyczyna jest systematyczna, nie przypadkowa: sekcja będzie pusta
    # dokładnie u tych klientów, u których historia jest najgęstsza.
    if not out_candidates and hidden_ineligible:
        reason_empty = "all_hidden_by_eligibility"

    return CandidatesFromSimilarOut(
        job_id=job_id,
        tier_used=tier_used,
        similar_jobs=[
            SimilarJobOut(
                job_id=r.job_id,
                title=r.title,
                similarity=r.similarity,
                tier=r.tier,
            )
            for r in similar_refs
        ],
        candidates=out_candidates,
        meta=HistoricalCandidatesMeta(
            tier_a_count=tier_a_count,
            tier_b_count=tier_b_count,
            total_sources=total_sources,
            reason_if_empty=reason_empty,
            hidden_ineligible=hidden_ineligible,
        ),
    )


# ── Candidate → jobs (reverse direction) ────────────────────────────────────


# Statuses eligible for candidate→job recommendations. Mirrors
# marketplace_service.scan_candidate_for_top_jobs ("otwarte joby"): draft +
# published, never closed. Including drafts means the widget isn't empty when
# few jobs are published yet (on prod ~14/3883 are published) — the same reason
# the "Wrzuć na targ" button finds matches the old published-only filter missed.
_RECOMMENDABLE_STATUSES = (JobStatus.draft, JobStatus.published)


def _recommendation_rank_key(
    total: float, status: JobStatus | None
) -> tuple[int, float]:
    """Ordering key for candidate→job recommendations: published first, by score.

    Published jobs are immediately actionable openings, so they rank ahead of
    drafts even when a draft scores higher — this keeps ``published`` the
    higher-priority signal while draft matches still surface below it. Within a
    single status bucket, higher score wins.
    """
    published_rank = 0 if status == JobStatus.published else 1
    return (published_rank, -total)


@router.get("/candidates/{candidate_id}/recommendations")
@limiter.limit("20/minute")
async def recommend_jobs_for_candidate(
    request: Request,
    candidate_id: int,
    top_k: int = Query(10, ge=1, le=50),
    include_breakdown: bool = Query(True),
    only_open: bool = Query(
        True,
        description=(
            "Restrict to open jobs — status draft OR published, never closed "
            "(mirrors the marketplace 'otwarte joby' filter). Set false to "
            "include closed jobs too. Published jobs are ranked above drafts."
        ),
    ),
    current_user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
):
    """Reverse recommendations: which open (draft/published) jobs fit this candidate?"""
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
    delivery_lead_client_ids = await resolve_delivery_lead_client_ids(current_user, db)
    include_finance = user_has_capability(
        current_user, AnalyticsCapability.VIEW_FINANCE
    )

    # Build a short query from candidate facets
    parts: List[str] = []
    if candidate.competence_category:
        parts.append(candidate.competence_category)
    if candidate.skills and isinstance(candidate.skills, list):
        for s in candidate.skills[:10]:
            if isinstance(s, dict) and s.get("name"):
                parts.append(s["name"])
            elif isinstance(s, str):
                parts.append(s)
    if candidate.ai_summary:
        parts.append(candidate.ai_summary[:300])
    query_text = " ".join(parts).strip() or f"{candidate.name} {candidate.lastname}"

    # Wide retrieval pool BEFORE the status filter — the jobs index holds all
    # statuses (mostly closed), so a narrow top-N can be 100% closed and starve
    # the published/draft intersection to zero (M3-JOB-01).
    # `raise_on_error=True` — bez tego awaria providera zwracała `[]`, czyli tę
    # samą wartość co zdrowe zapytanie bez trafień, a fallback niżej dolewał
    # 100 ARBITRALNYCH ofert (bez ORDER BY, z ~2857 opublikowanych). Były one
    # scorowane z pustą mapą podobieństwa, więc traciły całą wagę semantyczną
    # (60 ze 100 pkt) i wracały do rekrutera jako `matches` z HTTP 200. Ta sama
    # para kandydat/oferta miała przy zdrowym Qdrancie 80.6 pkt, a przy awarii
    # ~26 albo znikała z listy — a rekruter nie miał jak tego zauważyć.
    semantic_unavailable = False
    try:
        hits = await search_jobs_semantic(
            query_text,
            top_k=max(top_k * 4, settings.JOB_SEMANTIC_POOL_SIZE),
            raise_on_error=True,
        )
    except SemanticSearchUnavailable:
        logger.warning(
            "[recommendations] wyszukiwanie semantyczne niedostępne dla kandydata %s",
            candidate_id,
        )
        semantic_unavailable = True
        hits = []
    similarity_map = {h["job_id"]: h["score"] for h in hits}
    job_ids = list(similarity_map.keys())

    # Fallback dolewa oferty TYLKO wtedy, gdy wyszukiwanie odpowiedziało i nic
    # nie znalazło. Przy awarii lista losowych ofert podpisana „dopasowania"
    # jest gorsza niż brak listy: rekruter przypisuje kandydata do oferty
    # wybranej ze zbioru, który z dopasowaniem nie ma nic wspólnego.
    if not job_ids and not semantic_unavailable:
        open_job_query = select(Job.id).where(Job.status.in_(_RECOMMENDABLE_STATUSES))
        open_job_query = apply_delivery_lead_client_scope(
            open_job_query,
            Job.client_id,
            delivery_lead_client_ids,
        )
        # `ORDER BY` — bez niego „pierwsze 100" to arbitralny wycinek, inny
        # przy każdym wywołaniu.
        open_jobs = await db.execute(open_job_query.order_by(Job.id.desc()).limit(100))
        job_ids = [j for (j,) in open_jobs.all()]

    if not job_ids:
        return {
            "candidate_id": candidate_id,
            "candidate_name": f"{candidate.name} {candidate.lastname}",
            "matches": [],
            "meta": {
                "mode": "semantic" if not semantic_unavailable else "unavailable",
                "degraded": semantic_unavailable,
                "reason": (
                    "semantic_unavailable" if semantic_unavailable else "no_open_jobs"
                ),
            },
        }

    job_query = select(Job).where(Job.id.in_(job_ids))
    job_query = apply_delivery_lead_client_scope(
        job_query,
        Job.client_id,
        delivery_lead_client_ids,
    )
    if only_open:
        # "Open" = draft + published (matches scan_candidate_for_top_jobs);
        # closed jobs are never recommended.
        job_query = job_query.where(Job.status.in_(_RECOMMENDABLE_STATUSES))
    jobs = (await db.execute(job_query)).scalars().all()

    # Skip jobs already in this candidate's pipeline
    in_pipeline = await db.execute(
        select(CandidateStage.job_id)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id.in_([j.id for j in jobs]),
        )
        .distinct()
    )
    already = {jid for (jid,) in in_pipeline.all()}
    jobs = [j for j in jobs if j.id not in already]

    breakdowns = await rank_jobs_for_candidate(
        candidate, jobs, db, similarity_map=similarity_map
    )
    # Published roles outrank drafts (higher-priority signal); re-rank BEFORE the
    # top_k cap so published matches aren't truncated away by a score-only sort.
    status_by_job = {j.id: j.status for j in jobs}
    breakdowns.sort(
        key=lambda b: _recommendation_rank_key(b.total, status_by_job.get(b.job_id))
    )
    breakdowns = breakdowns[:top_k]

    matches = []
    for b in breakdowns:
        j = next((x for x in jobs if x.id == b.job_id), None)
        if not j:
            continue
        match = {
            "job": _shape_recommended_job(j, include_finance=include_finance),
            "total_score": round(b.total, 1),
        }
        if include_breakdown:
            match["breakdown"] = _score_breakdown_payload(
                b,
                include_finance=include_finance,
            )
        matches.append(match)

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "matches": matches,
        # Ten sam kształt, co w `GET /api/jobs/{id}/recommendations`
        # (matching.py) — front (`SuggestedJobsWidget`) ma już gotowy slot na
        # baner i czyta `recommendations.data?.meta`.
        "meta": {
            "mode": "unavailable" if semantic_unavailable else "semantic",
            "degraded": semantic_unavailable,
            "reason": "semantic_unavailable" if semantic_unavailable else None,
        },
    }


# ── AI-generated criteria (must/nice skills from description) ───────────────


async def _generate_criteria_with_ollama(job: Job) -> Optional[dict]:
    """Call local Ollama (if configured) to extract must/nice from description."""
    # Config only defines OLLAMA_BASE_URL; the legacy OLLAMA_HOST is never set,
    # so checking OLLAMA_HOST alone left this path permanently dead (always
    # falling through to the heuristic). Resolve both, mirroring cv_parser.
    ollama_host = getattr(settings, "OLLAMA_HOST", None) or getattr(
        settings, "OLLAMA_BASE_URL", None
    )
    if not ollama_host:
        return None
    model = getattr(settings, "OLLAMA_MODEL", "llama3.2")

    import httpx
    from app.services.llm_prompts import JOB_CRITERIA_FROM_DESCRIPTION

    prompt = JOB_CRITERIA_FROM_DESCRIPTION.render(
        title=job.title or "",
        description=(job.description or "")[:2000],
        requirements=(job.requirements or "")[:2000],
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{ollama_host.rstrip('/')}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
            )
            resp.raise_for_status()
            payload = resp.json().get("response", "").strip()
            import json

            data = json.loads(payload)
            if not isinstance(data, dict):
                return None
            # Stamp the source so refresh/preview can report "ollama" vs
            # "heuristic" (the endpoints key on ``"_source" in criteria``).
            # It is a top-level key, not part of must/nice, so it never leaks
            # into the persisted skill lists.
            return {
                "must_skills": data.get("must_skills") or [],
                "nice_skills": data.get("nice_skills") or [],
                "_source": (
                    f"ollama:{JOB_CRITERIA_FROM_DESCRIPTION.name}"
                    f":v{JOB_CRITERIA_FROM_DESCRIPTION.version}"
                ),
            }
    except Exception as e:
        logger.warning(
            "[Ollama] criteria generation failed (template=%s v%d): %s",
            JOB_CRITERIA_FROM_DESCRIPTION.name,
            JOB_CRITERIA_FROM_DESCRIPTION.version,
            e,
        )
        return None


def _fallback_criteria_from_text(job: Job) -> dict:
    """
    Very light heuristic fallback when Ollama is unavailable.

    Extracts only recognised technology tokens from title/description/
    requirements. It deliberately does NOT persist arbitrary requirement prose
    (e.g. "Bardzo dobra znajomość angielskiego") as a skill — the previous
    implementation dumped any ≤50-char non-tech line into ``nice_skills``,
    which polluted matching and downstream CV bolding. Tokens are de-duplicated
    in first-seen order (deterministic — the old ``set`` was not): the first 8
    become must-have, the next 6 nice-to-have.
    """
    TECH_PATTERN = re.compile(
        r"\b(Python|Java|JavaScript|TypeScript|React|Angular|Vue|Node|Go|Rust|C\+\+|C#|Kotlin|"
        r"Swift|PHP|Ruby|Scala|SQL|PostgreSQL|MySQL|MongoDB|Redis|Docker|Kubernetes|AWS|GCP|"
        r"Azure|Terraform|Kafka|RabbitMQ|Elasticsearch|Django|Flask|FastAPI|Spring|Express|"
        r"Next\.js|GraphQL|REST|gRPC|CI/CD|Git)\b",
        re.I,
    )
    text = " ".join(filter(None, [job.title, job.description, job.requirements]))
    seen: set[str] = set()
    ordered: list[str] = []
    for m in TECH_PATTERN.finditer(text):
        tok = m.group(0)
        key = tok.lower()
        if key not in seen:
            seen.add(key)
            ordered.append(tok)
    must = [{"name": n, "level": None} for n in ordered[:8]]
    nice = [{"name": n, "level": None} for n in ordered[8:14]]
    return {"must_skills": must, "nice_skills": nice}


@router.post(
    "/jobs/{job_id}/refresh-criteria",
    response_model=dict,
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
@limiter.limit("5/minute")
async def refresh_job_criteria(
    request: Request,
    job_id: int,
    current_user: User = Depends(_ADMIN_OR_DELIVERY_LEAD_CANDIDATE_WRITE),
    db: AsyncSession = Depends(get_db),
):
    """
    Regenerate job.must_skills + nice_skills from description (AI or fallback)
    and re-embed the job.
    """
    from datetime import datetime, timezone

    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    criteria = await _generate_criteria_with_ollama(job)
    if not criteria:
        criteria = _fallback_criteria_from_text(job)

    job.must_skills = criteria.get("must_skills") or []
    job.nice_skills = criteria.get("nice_skills") or []
    job.criteria_generated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(job)

    # Re-embed with fresh criteria
    try:
        await embed_job(job_id, db)
    except Exception as e:  # pragma: no cover
        logger.warning(f"[refresh-criteria] embed failed: {e}")

    return {
        "job_id": job_id,
        "must_skills": job.must_skills,
        "nice_skills": job.nice_skills,
        "criteria_generated_at": job.criteria_generated_at.isoformat(),
        "source": "ollama" if criteria and "_source" in criteria else "heuristic",
    }


@router.post("/jobs/{job_id}/generate-criteria-preview", response_model=dict)
@limiter.limit("5/minute")
async def generate_job_criteria_preview(
    request: Request,
    job_id: int,
    current_user: User = Depends(_ADMIN_OR_DELIVERY_LEAD_CANDIDATE_READ),
    db: AsyncSession = Depends(get_db),
):
    """
    Preview-only: generate proposed must/nice skills without persisting them.
    Client can then edit and PATCH /api/jobs/{id} with the approved list.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    criteria = await _generate_criteria_with_ollama(job)
    source = "ollama" if criteria and "_source" in criteria else "heuristic"
    if not criteria:
        criteria = _fallback_criteria_from_text(job)

    return {
        "job_id": job_id,
        "must_skills": criteria.get("must_skills") or [],
        "nice_skills": criteria.get("nice_skills") or [],
        "source": source,
        "current_must_skills": job.must_skills or [],
        "current_nice_skills": job.nice_skills or [],
    }


# ── Batch recompute ─────────────────────────────────────────────────────────


@router.post(
    "/jobs/{job_id}/recompute-scores",
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
@limiter.limit("2/minute")
async def recompute_scores(
    request: Request,
    job_id: int,
    top_k: int = Query(200, ge=1, le=500),
    current_user: User = Depends(_ADMIN_OR_DELIVERY_LEAD_CANDIDATE_WRITE),
    db: AsyncSession = Depends(get_db),
):
    """
    Recompute scores for top_k candidates and re-embed the job. Returns summary.
    Useful after updating must/nice skills or other matching-critical fields.
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    await embed_job(job_id, db)

    # Trigger a full recommendation pass (results not returned to keep payload
    # small). Calls the application-service core, NOT the route — the route is
    # wrapped by slowapi and takes a required `Request` plus `Query(...)`
    # defaults, so a direct route-to-route call crashes at runtime (M3-API-01).
    result = await _recommend_candidates_core(
        job_id,
        current_user=current_user,
        db=db,
        top_k=top_k,
        include_breakdown=False,
        exclude_in_pipeline=False,
        # Grzałka cache, nie widok użytkownika: ma policzyć/odświeżyć score'y
        # PEŁNEJ puli, także kandydatów powyżej budżetu — inaczej wyłączenie
        # sufitu w UI trafia na zimny cache (review #1207). Wyników i tak nie
        # zwracamy, więc default produktowy (ukrywaj) tu nie obowiązuje.
        exclude_over_budget=False,
    )

    return {
        "job_id": job_id,
        "evaluated": len(result.get("matches", [])),
        "status": "ok",
    }


# ── Assign to recruitment (quick action from candidate profile) ─────────────


@router.post(
    "/candidates/{candidate_id}/assign-to-job/{job_id}",
    dependencies=PIPELINE_SECTION_DEPENDENCIES,
)
async def assign_candidate_to_job(
    candidate_id: int,
    job_id: int,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """
    Add the candidate to a job's pipeline at the first (lowest-order) internal stage.
    No-op if the candidate already has a CandidateStage row for this job.
    """
    from datetime import datetime, timezone

    from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
    from app.models.recruitment_pipeline import PipelineStage

    from app.api.recruitment_access import ensure_job_membership

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Candidate or Job not found")

    # P0-A: resource scope — assigning a candidate into a job's pipeline is a
    # pipeline write, so the caller must belong to the job (owner / delivery lead
    # / TAC / active collaborator / priority assignment), exactly like the
    # shortlist and pipeline-move ingresses. Without this a recruiter could push
    # a candidate straight into a recruitment they are not a member of. Raises a
    # uniform 403 for non-members (admin / head_of_recruitment bypass).
    await ensure_job_membership(db, current_user, job_id)

    # Skip if already in pipeline
    existing = await db.scalar(
        select(func.count(CandidateStage.id)).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
    )
    if existing:
        return {"status": "already_in_pipeline", "count": existing}

    # Eligibility gate (SEARCH-P0-04) — same policy as bulk-add. Blocks the
    # assignment on global blacklist or an active, non-expired client conflict
    # (blacklist/nda/competitor) for this job's client. Soft signals
    # (current-employment, candidate-excluded) do NOT block a single assign.
    conflict_rows = (
        (
            await db.execute(
                select(CandidateConflict).where(
                    CandidateConflict.candidate_id == candidate_id,
                    CandidateConflict.client_id == job.client_id,
                    CandidateConflict.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    manager_verdicts = await load_manager_rejections(
        db, job=job, candidate_ids=[candidate_id]
    )
    eligibility = evaluate_eligibility(
        EligibilityInput(
            candidate_status=candidate.status.value,
            job_client_id=job.client_id,
            conflicts=tuple(
                ConflictInput(
                    type=r.type.value,
                    client_id=r.client_id,
                    active=r.active,
                    expires_at=r.expires_at,
                )
                for r in conflict_rows
            ),
            excluded_client_ids=extract_excluded_client_ids(candidate.preferences),
            already_in_job=False,  # already handled by the check above
            rejected_by_hiring_manager=candidate_id in manager_verdicts,
        ),
        datetime.now(timezone.utc),
    )
    if not eligibility.assignment_allowed:
        detail = eligibility.reason
        verdict = manager_verdicts.get(candidate_id)
        if (
            eligibility.reason_code is EligibilityReason.rejected_by_hiring_manager
            and verdict is not None
        ):
            # Name the manager and the date — otherwise the recruiter has to go
            # dig through the candidate's history to learn why.
            detail = verdict.as_polish_detail()
        raise HTTPException(status_code=409, detail=detail)

    # Resolve initial stage from the job's template
    template_id = job.pipeline_template_id
    if not template_id:
        template_id = await db.scalar(
            select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
        )

    first_stage = None
    if template_id:
        first_stage = await db.scalar(
            select(PipelineStageDef)
            .where(PipelineStageDef.template_id == template_id)
            .order_by(PipelineStageDef.order)
            .limit(1)
        )

    legacy_enum = PipelineStage.new
    if first_stage and first_stage.legacy_enum_value:
        try:
            legacy_enum = PipelineStage(first_stage.legacy_enum_value)
        except ValueError:
            legacy_enum = PipelineStage.new

    stage = await open_process(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        stage=legacy_enum,
        stage_def_id=first_stage.id if first_stage else None,
        moved_at=datetime.now(timezone.utc),
        actor_user_id=current_user.id,
        work_channel=PriorityChannel.database,
    )
    await create_original_cv_snapshot(db, stage)
    await maybe_ensure_contact_opportunity(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        source="pipeline",
        occurred_at=stage.moved_at,
    )
    await db.commit()
    await db.refresh(stage)

    # P0-B: record the pipeline-entry outcome for match telemetry (no-op unless
    # AI_MATCH_TELEMETRY_ENABLED), correlated with the job's latest ranking run.
    from app.services.match_telemetry_service import emit_match_outcome

    await emit_match_outcome(
        db, event_type="add_to_pipeline", candidate_id=candidate_id, job_id=job_id
    )

    return {
        "status": "assigned",
        "candidate_id": candidate_id,
        "job_id": job_id,
        "stage_id": stage.id,
        "stage_def_id": stage.stage_def_id,
    }


# CV → jobs preview lives in `cv_match_preview.py` (separate module so its
# `multipart/form-data` endpoint is not affected by `from __future__ import
# annotations` here, which trips FastAPI's `Annotated[UploadFile, File(...)]`
# resolution).


# ── Seeking-contractors batch ───────────────────────────────────────────────


def _candidate_query_text(candidate: Candidate) -> str:
    """Build embedding query text from a Candidate ORM row.

    Mirrors `embedding_service._build_candidate_text` but is co-located here so
    the seeking-contractors endpoint doesn't depend on a private helper.
    """
    parts: list[str] = []
    if candidate.competence_category:
        parts.append(candidate.competence_category)
    years = getattr(candidate, "years_it_experience", None)
    if isinstance(years, int):
        if years >= 7:
            parts.append("senior experienced engineer")
        elif years >= 3:
            parts.append("mid-level developer")
        else:
            parts.append("junior entry-level developer")
    if candidate.skills and isinstance(candidate.skills, list):
        for s in candidate.skills[:15]:
            if isinstance(s, dict) and s.get("name"):
                parts.append(s["name"])
            elif isinstance(s, str):
                parts.append(s)
    if candidate.ai_summary:
        parts.append(candidate.ai_summary[:300])
    if not parts:
        parts.append(f"{candidate.name} {candidate.lastname}")
    return " ".join(p for p in parts if p and str(p).strip())


def _shape_seek_candidate(c: Candidate) -> dict:
    """Trim a Candidate ORM row to the seeking-contractors public shape."""
    return {
        "id": c.id,
        "name": c.name,
        "lastname": c.lastname,
        "email": c.email,
        "location": c.location,
        "competence_category": c.competence_category,
        "years_it_experience": c.years_it_experience,
        "availability_status": (
            c.availability_status.value if c.availability_status else None
        ),
        "champion": c.champion,
        "avatar_url": c.avatar_url,
    }


def _shape_seek_job(j: Job, *, include_finance: bool = False) -> dict:
    return {
        "id": j.id,
        "title": j.title,
        "client_id": j.client_id,
        "location": j.location,
        "salary_min": j.salary_min if include_finance else None,
        "salary_max": j.salary_max if include_finance else None,
        "remote_policy": j.remote_policy.value if j.remote_policy else None,
        "seniority": j.seniority.value if j.seniority else None,
        "deadline": j.deadline.isoformat() if j.deadline else None,
    }


def seeking_priority(
    candidate_id: int, ending_meta: dict[int, dict]
) -> tuple[int, str, int]:
    """Klucz porządkujący pulę „Szukają projektu" PRZED obcięciem do strony.

    Na poziomie modułu, nie jako domknięcie w handlerze, bo to jest reguła
    decydująca o tym, KTO przetrwa cięcie — test musi sprawdzać dokładnie tę
    funkcję, a nie jej kopię (kopia przestaje cokolwiek chronić w momencie,
    w którym oryginał się zmieni).

    Pełny klucz wymagałby scoringu, którego nie policzymy dla całej puli. Ale
    kryterium pierwszorzędne — pilność — znamy przed scoringiem: kontrakt
    kończy się wcześniej ⇒ wyżej. ``candidate_id`` domyka porządek, żeby wynik
    był powtarzalny między requestami.

    ``contract_end_date`` jest tu zawsze ustawiona: zapytanie budujące
    ``ending_meta`` filtruje ``Contract.end_date.is_not(None)``.
    """
    meta = ending_meta.get(candidate_id)
    if meta is None:
        return (1, "", candidate_id)  # bez kontraktu — po tych kończących się
    return (0, meta["contract_end_date"].isoformat(), candidate_id)


@router.get("/recommendations/seeking-contractors")
@limiter.limit("20/minute")
async def seeking_contractors(
    request: Request,
    horizon_days: int = Query(
        30, ge=1, le=180, description="Window for `Contract.end_date` (days)."
    ),
    top_k: int = Query(5, ge=1, le=20, description="Top jobs per candidate."),
    threshold: float = Query(
        40.0,
        ge=0.0,
        le=100.0,
        description="Total score below which jobs are rolled into `below_threshold_count`.",
    ),
    location: Optional[str] = Query(None),
    salary_min: Optional[int] = Query(None),
    salary_max: Optional[int] = Query(None),
    competence_category: Optional[list[str]] = Query(
        None,
        description=(
            "Filter by competence category — one or more values. Repeat the "
            "param for multi-select (e.g. `?competence_category=Backend"
            "&competence_category=DevOps`). OR-combined (any match keeps the job)."
        ),
    ),
    industry_blocklist: bool = Query(
        True,
        description=(
            "Soft-warnings toggle ONLY (e.g. „obecnie u tego klienta”). Hard "
            "NDA/blacklist/competitor conflicts are enforced server-side "
            "regardless of this flag (M2 audit PR 1, fail-closed)."
        ),
    ),
    page_size: int = Query(50, ge=1, le=200),
    current_user: User = Depends(require_candidate_read),
    db: AsyncSession = Depends(get_db),
):
    """Konsultanci szukający projektu — batch matcher.

    Pool is the union of:
      - candidates with active/draft/ending Contract whose `end_date` falls
        within `horizon_days`
      - candidates whose `availability_status` is `actively_looking` or
        `open_to_offers`

    For each candidate, runs the same hybrid scoring as the per-candidate
    `/recommendations` endpoint but caps results at `top_k` per row and reports
    a `below_threshold_count` for matches < `threshold`.

    Performance: jobs are prefetched once (single SQL `IN (...)`) and shared
    across all candidates. Per-candidate cost is one Voyage embed + one Qdrant
    search — the unavoidable minimum for personalized ranking.
    """
    from datetime import date, timedelta

    from app.models.contract import Contract, ContractStatus
    from app.services.recommendation_filters import (
        RecommendationFilters,
        apply_user_filters,
    )

    _assert_salary_filter_access(
        current_user,
        salary_min=salary_min,
        salary_max=salary_max,
    )
    include_finance = user_has_capability(
        current_user, AnalyticsCapability.VIEW_FINANCE
    )
    delivery_lead_client_ids = await resolve_delivery_lead_client_ids(current_user, db)

    # 1. Build the candidate pool (union of two sources).
    horizon = date.today() + timedelta(days=horizon_days)

    # Source A: contractors with end_date within horizon (status active or ending)
    ending_query = select(
        Contract.candidate_id,
        Contract.end_date,
        Contract.client_id,
    ).where(
        Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
        Contract.end_date.is_not(None),
        Contract.end_date <= horizon,
    )
    ending_query = apply_delivery_lead_client_scope(
        ending_query,
        Contract.client_id,
        delivery_lead_client_ids,
    )
    ending_rows = await db.execute(ending_query)
    ending_meta: dict[int, dict] = {}
    for cid, end_date, client_id in ending_rows.all():
        existing = ending_meta.get(cid)
        # Keep the earliest end_date if multiple contracts.
        if not existing or end_date < existing["contract_end_date"]:
            ending_meta[cid] = {
                "contract_end_date": end_date,
                "current_client_id": client_id,
            }

    # Source B: candidates with availability_status in the "looking" set
    looking_ids: set[int] = set()
    if delivery_lead_client_ids is None:
        looking_rows = await db.execute(
            select(Candidate.id).where(
                Candidate.availability_status.in_(
                    [
                        AvailabilityStatus.actively_looking,
                        AvailabilityStatus.open_to_offers,
                    ]
                ),
                Candidate.status != CandidateStatus.blacklisted,
            )
        )
        looking_ids = {row[0] for row in looking_rows.all()}

    # Pełna pula PRZED obcięciem — `total` musi opisywać ilu jest konsultantów,
    # nie ile ich zmieściło się na stronie. Wcześniej `total` liczyło już
    # obciętą listę, więc UI pokazywał „18 konsultantów w horyzoncie 30 dni"
    # niezależnie od tego, czy było ich 18 czy 400.
    pool_ids = set(ending_meta.keys()) | looking_ids
    total_available = len(pool_ids)

    # Kolejność PRZED obcięciem, nie po. Wcześniej brane było `list(set(...))`,
    # czyli porządek iteracji zbioru — a właściwe sortowanie („kończące się
    # kontrakty najpierw") wykonywało się dopiero na tym, co zostało po cięciu.
    # Konsultant z kontraktem kończącym się jutro mógł więc po prostu nie
    # zmieścić się w arbitralnym wycinku i zniknąć z ekranu bez śladu.
    #
    # Pełny klucz sortowania wymaga scoringu, którego nie policzymy dla całej
    # puli. Ale kryterium PIERWSZORZĘDNE — pilność — znamy już teraz: kontrakt
    # kończy się wcześniej ⇒ wyżej. `id` domyka porządek, żeby wynik był
    # powtarzalny między requestami.
    candidate_ids = sorted(
        pool_ids, key=lambda cid: seeking_priority(cid, ending_meta)
    )[:page_size]

    if not candidate_ids:
        return {
            "horizon_days": horizon_days,
            "total": 0,
            "returned": 0,
            "truncated": False,
            "items": [],
            # `meta` jest w KAŻDEJ gałęzi, także tam, gdzie wyszukiwanie się nie
            # odbyło. Konsument czytający `body.meta.degraded` dostawał tu
            # `undefined`, czyli wartość fałszywą — przypadkiem poprawną, ale
            # nie do odróżnienia od „sprawdziliśmy i jest dobrze". Odpowiedź,
            # która raz niesie sygnał uczciwości, a raz go milcząco pomija, każe
            # konsumentowi zgadywać, którą wersję właśnie dostał.
            "meta": {"degraded": False, "reason": "no_candidates"},
        }

    cand_res = await db.execute(
        select(Candidate).where(Candidate.id.in_(candidate_ids))
    )
    candidates = cand_res.scalars().all()

    # 2. Prefetch all open jobs once.
    open_jobs_query = select(Job).where(Job.status == JobStatus.published)
    open_jobs_query = apply_delivery_lead_client_scope(
        open_jobs_query,
        Job.client_id,
        delivery_lead_client_ids,
    )
    jobs_res = await db.execute(open_jobs_query)
    all_open_jobs = list(jobs_res.scalars().all())

    if not all_open_jobs:
        return {
            "horizon_days": horizon_days,
            "total": total_available,
            "returned": len(candidate_ids),
            "truncated": total_available > len(candidate_ids),
            "items": [
                {
                    "candidate": _shape_seek_candidate(c),
                    "source": (
                        "ending_contract"
                        if c.id in ending_meta
                        else "availability_status"
                    ),
                    "contract_end_date": (
                        ending_meta[c.id]["contract_end_date"].isoformat()
                        if c.id in ending_meta
                        else None
                    ),
                    "top_matches": [],
                    "below_threshold_count": 0,
                }
                for c in candidates
            ],
            # Jak wyżej — pusty wynik z powodu braku ofert to inne zdanie niż
            # pusty wynik z powodu awarii, a bez `meta` oba wyglądają tak samo.
            # Nazwa powodu jest lustrem `no_open_jobs` z endpointu wyżej w tym
            # samym pliku.
            "meta": {"degraded": False, "reason": "no_open_jobs"},
        }

    user_filters = RecommendationFilters(
        location=location,
        salary_min=salary_min,
        salary_max=salary_max,
        competence_category=competence_category,
        industry_blocklist=industry_blocklist,
    )

    items: list[dict] = []
    bulk_degraded = False
    for cand in candidates:
        # 2a. Personalized Qdrant search — narrow to a candidate-relevant pool.
        # Wide pool BEFORE the published-intersection (M3-JOB-01): the jobs
        # index holds all statuses (mostly closed), so a narrow top-N could be
        # 100% closed and the published intersection starved to zero.
        query_text = _candidate_query_text(cand)
        # Jak wyżej: awaria providera nie może udawać „nic nie znaleziono", bo
        # fallback niżej dolewa 50 arbitralnych ofert scorowanych bez warstwy
        # semantycznej. Tu dodatkowo idziemy w PĘTLI po kandydatach — jedna
        # awaria zamieniłaby cały kokpit w listę losowych par.
        try:
            hits = await search_jobs_semantic(
                query_text,
                top_k=settings.JOB_SEMANTIC_POOL_SIZE,
                raise_on_error=True,
            )
            cand_semantic_ok = True
        except SemanticSearchUnavailable:
            hits = []
            cand_semantic_ok = False
            bulk_degraded = True
        similarity_map: dict[int, float] = {h["job_id"]: h["score"] for h in hits}

        # Restrict scoring to (a) Qdrant hits ∩ open jobs OR (b) all open jobs
        # when Qdrant is empty/offline. Either way keep a small pool.
        if similarity_map:
            scoring_pool = [j for j in all_open_jobs if j.id in similarity_map]
        elif cand_semantic_ok:
            # Fallback: rank against the full open-jobs set, capped to keep
            # response time predictable for the dashboard. Odpala się WYŁĄCZNIE
            # wtedy, gdy wyszukiwanie odpowiedziało i nic nie znalazło.
            scoring_pool = all_open_jobs[:50]
        else:
            # Awaria wyszukiwania — żadnych propozycji dla tego kandydata.
            # Pusty wiersz z flagą degradacji jest uczciwszy niż wiersz
            # wypełniony losowymi ofertami.
            scoring_pool = []

        # 2b. Apply user filters (incl. industry_blocklist via CandidateConflict)
        filtered, _stats = await apply_user_filters(
            cand, scoring_pool, user_filters, db
        )
        warning_by_job = {fj.job.id: fj.warning for fj in filtered}

        breakdowns = await rank_jobs_for_candidate(
            cand,
            [fj.job for fj in filtered],
            db,
            similarity_map=similarity_map,
        )

        above = [b for b in breakdowns if b.total >= threshold]
        below_count = sum(1 for b in breakdowns if b.total < threshold)

        top_matches = []
        for b in above[:top_k]:
            j = next((x.job for x in filtered if x.job.id == b.job_id), None)
            if not j:
                continue
            top_matches.append(
                {
                    "job": _shape_seek_job(j, include_finance=include_finance),
                    "total_score": round(b.total, 1),
                    "breakdown": _score_breakdown_payload(
                        b,
                        include_finance=include_finance,
                    ),
                    "warning": warning_by_job.get(j.id),
                }
            )

        meta = ending_meta.get(cand.id)
        items.append(
            {
                "candidate": _shape_seek_candidate(cand),
                "source": "ending_contract" if meta else "availability_status",
                "contract_end_date": (
                    meta["contract_end_date"].isoformat() if meta else None
                ),
                "current_client_id": meta["current_client_id"] if meta else None,
                "top_matches": top_matches,
                "below_threshold_count": below_count,
            }
        )

    # 3. Sort: ending contracts first (urgent), then by top-match score desc.
    def _sort_key(it: dict):
        is_ending = 0 if it["source"] == "ending_contract" else 1
        top_score = it["top_matches"][0]["total_score"] if it["top_matches"] else 0.0
        return (is_ending, -top_score)

    items.sort(key=_sort_key)

    return {
        "horizon_days": horizon_days,
        # Ilu ich JEST, nie ilu się zmieściło — te dwie liczby rozjeżdżały się
        # cicho, a UI pokazywał tę drugą jako pierwszą.
        "total": total_available,
        "returned": len(items),
        "truncated": total_available > len(items),
        "items": items,
        # Jeśli dla CHOĆ JEDNEGO kandydata wyszukiwanie nie odpowiedziało,
        # kokpit jest niepełny — i musi to powiedzieć. Bez tego pusty wiersz
        # przy awarii czyta się jak „dla tej osoby nie ma nic sensownego".
        "meta": {
            "degraded": bulk_degraded,
            "reason": "semantic_unavailable" if bulk_degraded else None,
        },
    }
