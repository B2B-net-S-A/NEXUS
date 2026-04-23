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

from app.api.deps import (
    CurrentUser,
    get_current_user,
    require_roles,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.user import User, UserRole
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.services.embedding_service import (
    _build_job_text,
    embed_job,
    search_candidates_semantic,
    search_jobs_semantic,
)
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    WeightProfile,
    rank_jobs_for_candidate,
    resolve_active_profile,
)
from app.services.match_score_cache import bulk_get_or_compute
from app.services.similar_job_candidates import (
    boost_points_for_sources,
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

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Job → candidates (explainable) ──────────────────────────────────────────


@router.get("/jobs/{job_id}/recommendations")
@limiter.limit("20/minute")
async def recommend_candidates_for_job(
    request: Request,
    job_id: int,
    top_k: int = Query(20, ge=1, le=100),
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Top-K ranking of candidates for a job using hybrid scoring
    (semantic 40 + skills 30 + salary 15 + location 10 + availability 5 − penalties).
    """
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

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

    query_text = _build_job_text(job)

    # Pull a wider candidate pool from Qdrant, then re-rank with rules
    pool_size = min(top_k * 4, 200)
    hits = await search_candidates_semantic(query_text, top_k=pool_size)
    similarity_map = {h["candidate_id"]: h["score"] for h in hits}
    candidate_ids = list(similarity_map.keys())

    # Fallback when Qdrant is empty — widen to all active candidates (cap 200)
    if not candidate_ids:
        fallback = await db.execute(
            select(Candidate.id)
            .where(Candidate.status != CandidateStatus.blacklisted)
            .limit(200)
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
            "matches": [],
        }

    cand_res = await db.execute(
        select(Candidate).where(Candidate.id.in_(candidate_ids))
    )
    candidates = cand_res.scalars().all()

    # Phase C1 + D1: cache-first scoring keyed by active profile.
    breakdowns = await bulk_get_or_compute(
        job, candidates, db, similarity_map=similarity_map, profile=profile
    )

    # Phase 14: apply historical-boost from semantically-similar past jobs.
    # Computed fresh per request — not persisted in match-score cache because
    # candidate pipeline state changes too often to invalidate reliably.
    try:
        boost_map = await fetch_historical_boost_map(db, job_id)
    except Exception as e:  # pragma: no cover — best-effort
        logger.warning("historical_boost lookup failed for job=%s: %s", job_id, e)
        boost_map = {}
    if boost_map:
        for b in breakdowns:
            count = boost_map.get(b.candidate_id, 0)
            if count <= 0:
                continue
            bonus = boost_points_for_sources(count)
            b.historical_boost = bonus
            b.historical_sources_count = count
            b.total = round(b.total + bonus, 2)
        breakdowns.sort(key=lambda r: -r.total)

    breakdowns = breakdowns[:top_k]

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
                "salary_expectation": c.salary_expectation,
                "salary_currency": c.salary_currency,
                "years_it_experience": c.years_it_experience,
                "champion": c.champion,
                "avatar_url": c.avatar_url,
                "tags": c.tags,
                "skills": c.skills,
                "ai_summary": c.ai_summary,
            },
            "total_score": round(b.total, 1),
        }
        if include_breakdown:
            match["breakdown"] = b.as_dict()
        matches.append(match)

    return {
        "job_id": job_id,
        "job_title": job.title,
        "search_type": "hybrid",
        "profile": {"id": profile.id, "name": profile.name},
        "matches": matches,
    }


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
    current_user: User = Depends(get_current_user),
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
    )

    total_sources = sum(len(c.sources) for c in ranked)
    tier_a_count = sum(1 for r in similar_refs if r.tier == "A")
    tier_b_count = sum(1 for r in similar_refs if r.tier == "B")

    if not similar_refs:
        return CandidatesFromSimilarOut(
            job_id=job_id,
            tier_used="empty",
            similar_jobs=[],
            candidates=[],
            meta=HistoricalCandidatesMeta(
                tier_a_count=0,
                tier_b_count=0,
                total_sources=0,
                reason_if_empty="no_similar_jobs_found",
            ),
        )

    reason_empty: Optional[str] = None
    if not ranked:
        reason_empty = "no_pipeline_history_on_similar_jobs"

    # Hydrate candidate records (name, avatar, availability) in a single query.
    cand_ids = [c.candidate_id for c in ranked]
    cand_rows: list[Candidate] = []
    if cand_ids:
        cand_res = await db.execute(
            select(Candidate).where(Candidate.id.in_(cand_ids))
        )
        cand_rows = list(cand_res.scalars().all())
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
                    )
                    for s in hc.sources
                ],
                current_availability=_derive_availability(c),  # type: ignore[arg-type]
                current_status=c.status.value if c.status else None,
            )
        )

    out_candidates.sort(key=_availability_sort_key)

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
        ),
    )


# ── Candidate → jobs (reverse direction) ────────────────────────────────────


@router.get("/candidates/{candidate_id}/recommendations")
@limiter.limit("20/minute")
async def recommend_jobs_for_candidate(
    request: Request,
    candidate_id: int,
    top_k: int = Query(10, ge=1, le=50),
    include_breakdown: bool = Query(True),
    only_open: bool = Query(True, description="Only jobs with status=published."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Reverse recommendations: which open jobs fit this candidate?"""
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

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

    hits = await search_jobs_semantic(query_text, top_k=top_k * 4)
    similarity_map = {h["job_id"]: h["score"] for h in hits}
    job_ids = list(similarity_map.keys())

    # Fallback: all open jobs
    if not job_ids:
        open_jobs = await db.execute(
            select(Job.id).where(Job.status == JobStatus.published).limit(100)
        )
        job_ids = [j for (j,) in open_jobs.all()]

    if not job_ids:
        return {
            "candidate_id": candidate_id,
            "candidate_name": f"{candidate.name} {candidate.lastname}",
            "matches": [],
        }

    job_query = select(Job).where(Job.id.in_(job_ids))
    if only_open:
        job_query = job_query.where(Job.status == JobStatus.published)
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
    breakdowns = breakdowns[:top_k]

    matches = []
    for b in breakdowns:
        j = next((x for x in jobs if x.id == b.job_id), None)
        if not j:
            continue
        match = {
            "job": {
                "id": j.id,
                "title": j.title,
                "client_id": j.client_id,
                "location": j.location,
                "salary_min": j.salary_min,
                "salary_max": j.salary_max,
                "remote_policy": j.remote_policy.value if j.remote_policy else None,
                "status": j.status.value if j.status else None,
                "priority": j.priority.value if j.priority else None,
                "seniority": j.seniority.value if j.seniority else None,
                "industry": j.industry,
                "deadline": j.deadline.isoformat() if j.deadline else None,
            },
            "total_score": round(b.total, 1),
        }
        if include_breakdown:
            match["breakdown"] = b.as_dict()
        matches.append(match)

    return {
        "candidate_id": candidate_id,
        "candidate_name": f"{candidate.name} {candidate.lastname}",
        "matches": matches,
    }


# ── AI-generated criteria (must/nice skills from description) ───────────────


async def _generate_criteria_with_ollama(job: Job) -> Optional[dict]:
    """Call local Ollama (if configured) to extract must/nice from description."""
    ollama_host = getattr(settings, "OLLAMA_HOST", None)
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
            return {
                "must_skills": data.get("must_skills") or [],
                "nice_skills": data.get("nice_skills") or [],
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
    Splits requirements/description into bullet-ish lines and picks tech-ish keywords.
    """
    TECH_PATTERN = re.compile(
        r"\b(Python|Java|JavaScript|TypeScript|React|Angular|Vue|Node|Go|Rust|C\+\+|C#|Kotlin|"
        r"Swift|PHP|Ruby|Scala|SQL|PostgreSQL|MySQL|MongoDB|Redis|Docker|Kubernetes|AWS|GCP|"
        r"Azure|Terraform|Kafka|RabbitMQ|Elasticsearch|Django|Flask|FastAPI|Spring|Express|"
        r"Next\.js|GraphQL|REST|gRPC|CI/CD|Git)\b",
        re.I,
    )
    text = " ".join(filter(None, [job.title, job.description, job.requirements]))
    found = {m.group(0) for m in TECH_PATTERN.finditer(text)}
    must = [{"name": n, "level": None} for n in list(found)[:8]]
    # Read additional bullet lines for nice-to-have
    nice: list[dict] = []
    for line in (job.requirements or "").splitlines():
        line = line.strip().lstrip("•-–*·").strip()
        if 3 <= len(line) <= 50 and not TECH_PATTERN.search(line):
            nice.append({"name": line, "level": None})
        if len(nice) >= 6:
            break
    return {"must_skills": must, "nice_skills": nice}


@router.post("/jobs/{job_id}/refresh-criteria", response_model=dict)
@limiter.limit("5/minute")
async def refresh_job_criteria(
    request: Request,
    job_id: int,
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.delivery_lead)),
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
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.delivery_lead)),
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


@router.post("/jobs/{job_id}/recompute-scores")
@limiter.limit("2/minute")
async def recompute_scores(
    request: Request,
    job_id: int,
    top_k: int = Query(200, ge=1, le=500),
    current_user: User = Depends(require_roles(UserRole.admin, UserRole.delivery_lead)),
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

    # Trigger a full recommendation pass (results not returned to keep payload small)
    result = await recommend_candidates_for_job(
        job_id=job_id,
        current_user=current_user,
        top_k=top_k,
        include_breakdown=False,
        exclude_in_pipeline=False,
        db=db,
    )

    return {
        "job_id": job_id,
        "evaluated": len(result.get("matches", [])),
        "status": "ok",
    }


# ── Assign to recruitment (quick action from candidate profile) ─────────────


@router.post("/candidates/{candidate_id}/assign-to-job/{job_id}")
async def assign_candidate_to_job(
    candidate_id: int,
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Add the candidate to a job's pipeline at the first (lowest-order) internal stage.
    No-op if the candidate already has a CandidateStage row for this job.
    """
    from datetime import datetime, timezone

    from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
    from app.models.recruitment_pipeline import PipelineStage

    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    job = await db.scalar(select(Job).where(Job.id == job_id))
    if not candidate or not job:
        raise HTTPException(status_code=404, detail="Candidate or Job not found")

    # Skip if already in pipeline
    existing = await db.scalar(
        select(func.count(CandidateStage.id)).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
    )
    if existing:
        return {"status": "already_in_pipeline", "count": existing}

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

    stage = CandidateStage(
        candidate_id=candidate_id,
        job_id=job_id,
        stage=legacy_enum,
        stage_def_id=first_stage.id if first_stage else None,
        moved_at=datetime.now(timezone.utc),
        moved_by=current_user.id,
    )
    db.add(stage)
    await db.commit()
    await db.refresh(stage)

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
