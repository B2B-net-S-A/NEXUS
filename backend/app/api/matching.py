"""
AI Candidate Matching — dla danej oferty pracy, znajduje najlepiej pasujących kandydatów
używając semantycznego wyszukiwania Qdrant (Voyage AI) + fallback tag-based.

GET /api/jobs/{id}/ai-matches
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, CurrentUser
from app.core.config import settings
from app.models.candidate import Candidate
from app.models.job import Job
from app.services.location_utils import (
    location_matches as _location_matches,
    location_tokens as _location_tokens,
)
from app.services.reranker_service import rerank_or_passthrough

logger = logging.getLogger(__name__)
router = APIRouter()


def _normalize_skill(s) -> str:
    """Normalize a skill to lowercase string."""
    if isinstance(s, dict):
        return (s.get("name") or "").lower().strip()
    return str(s).lower().strip()


def _extract_skills(raw) -> list[str]:
    """Extract skill list from JSONB field (list of dicts or list of strings)."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [_normalize_skill(s) for s in raw if _normalize_skill(s)]
    if isinstance(raw, str):
        return [s.strip().lower() for s in raw.split(",") if s.strip()]
    return []


def _extract_tags(raw) -> list[str]:
    """Extract tags list."""
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(t).lower().strip() for t in raw if t]
    if isinstance(raw, str):
        return [t.strip().lower() for t in raw.split(",") if t.strip()]
    return []


def _build_match_info(
    candidate: Candidate,
    required_skills: list[str],
    score: float | None = None,
) -> dict:
    """Build the match result dict for a candidate."""
    c_skills = _extract_skills(candidate.skills)
    c_tags = _extract_tags(candidate.tags)
    all_candidate_skills = set(c_skills + c_tags)

    req_set = set(s.lower() for s in required_skills if s)

    matching = sorted(req_set & all_candidate_skills)
    gaps = sorted(req_set - all_candidate_skills)

    # Compute score if not provided by Qdrant
    if score is None:
        if req_set:
            score = len(matching) / len(req_set)
        else:
            # Fallback score based on profile completeness
            filled = sum(
                [
                    bool(candidate.skills),
                    bool(candidate.ai_summary),
                    bool(candidate.competence_category),
                    bool(candidate.email),
                ]
            )
            score = filled / 4

    return {
        "candidate": {
            "id": candidate.id,
            "name": candidate.name,
            "lastname": candidate.lastname,
            "email": candidate.email,
            "phone": candidate.phone,
            "location": candidate.location,
            "status": candidate.status.value if candidate.status else None,
            "competence_category": candidate.competence_category,
            "salary_expectation": candidate.salary_expectation,
            "salary_currency": candidate.salary_currency,
            "tags": candidate.tags,
            "skills": candidate.skills,
            "ai_summary": candidate.ai_summary,
            "avatar_url": candidate.avatar_url,
        },
        "match_score": round(min(score, 1.0), 3),
        "matching_skills": matching,
        "gaps": gaps,
    }


def _build_job_query(job: Job) -> str:
    """Build a semantic query string from job fields."""
    parts: list[str] = []

    if job.title:
        parts.append(job.title)

    # Extract required skills from requirements text and JSONB
    if job.requirements:
        parts.append(job.requirements[:500])

    if job.description:
        parts.append(job.description[:300])

    # Add seniority hint
    title_lower = (job.title or "").lower()
    if "senior" in title_lower:
        parts.append("senior experienced engineer")
    elif "junior" in title_lower:
        parts.append("junior developer entry level")
    elif "lead" in title_lower or "architect" in title_lower:
        parts.append("lead architect technical leadership")
    elif "mid" in title_lower:
        parts.append("mid level developer")

    return " ".join(p for p in parts if p.strip())


def _parse_required_skills(job: Job) -> list[str]:
    """Extract required skills from job requirements text."""
    skills: list[str] = []
    if not job.requirements:
        return skills
    for line in job.requirements.splitlines():
        line = line.strip().lstrip("•-–*·").strip()
        if line and 2 <= len(line) <= 60:
            skills.append(line.lower())
    return skills[:20]


@router.get("/jobs/{job_id}/ai-matches")
async def get_ai_matches(
    job_id: int,
    current_user: CurrentUser,
    min_score: float | None = None,
    limit: int | None = None,
    location: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    GET /api/jobs/{job_id}/ai-matches

    Returns **all** candidates that match the job (score >= ``min_score``),
    ranked best-first, using Qdrant semantic search + optional Voyage rerank.
    Falls back to tag-based matching if Qdrant is unavailable.

    Replaces the old hard top-10 behaviour: the result set is now bounded only
    by the match threshold and a safety cap (``MATCH_MAX_RESULTS``), so a job
    with 60 genuine fits shows all 60 instead of an arbitrary first 10.

    Query params (all optional; default to runtime-tunable settings):
        min_score: minimum match score (0-1) a candidate must reach to be shown.
        limit:     hard cap on the number of results (payload safety bound).
        location:  restrict results to candidates whose location matches this
                   place (city/region, substring-tolerant). Falls back to the
                   job's own ``location`` when omitted. Empty when neither is
                   set → no location filter (legacy behaviour preserved).
    """
    threshold = min_score if min_score is not None else settings.AI_MATCH_MIN_SCORE
    max_results = limit if limit is not None else settings.MATCH_MAX_RESULTS
    # Retrieval/rerank pool is independent of the result cap: it bounds how many
    # candidates the (cost-bearing) reranker scores, while max_results bounds the
    # payload. Results are therefore effectively capped at the smaller of the two.
    pool_size = settings.AI_MATCH_POOL_SIZE

    # Fetch job
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Oferta pracy nie istnieje")

    query_text = _build_job_query(job)
    required_skills = _parse_required_skills(job)

    # ── Location filter ──────────────────────────────────────────────────────
    # Explicit query param wins; otherwise fall back to the job's own location
    # (which is empty for ~99% of Traffit-imported jobs, hence the param).
    requested_location = (location or "").strip() or (job.location or "").strip()
    requested_tokens = _location_tokens(requested_location)
    location_active = bool(requested_tokens)
    # When filtering by location, widen the retrieval pool so the located subset
    # isn't starved by the default top-100 semantic cut (only ~17% of candidates
    # have any location at all). Plain (no-location) requests keep the cheaper
    # default pool.
    effective_pool = max(pool_size, max_results) if location_active else pool_size

    # ── Attempt Qdrant semantic search (+ optional Voyage rerank) ────────────
    try:
        from app.services.embedding_service import (
            _build_candidate_text,
            search_candidates_semantic,
        )

        # Pull a wide pool so "show all who match" isn't artificially capped by
        # retrieval. The threshold filter below — not a fixed top-K — decides
        # who is shown. Rerank cost scales ~linearly with pool size, hence the
        # tunable AI_MATCH_POOL_SIZE.
        rerank_enabled = bool(getattr(settings, "RERANKER_ENABLED", False))
        hits = await search_candidates_semantic(query_text, top_k=effective_pool)

        if hits:
            candidate_ids = [h["candidate_id"] for h in hits]
            qdrant_scores = {h["candidate_id"]: h["score"] for h in hits}

            cand_result = await db.execute(
                select(Candidate).where(Candidate.id.in_(candidate_ids))
            )
            candidates_by_id = {c.id: c for c in cand_result.scalars().all()}

            # Preserve Qdrant ranking order while filtering missing/blacklisted.
            ordered: list[Candidate] = []
            for cid in candidate_ids:
                c = candidates_by_id.get(cid)
                if not c:
                    continue
                status = c.status.value if c.status else None
                if status == "blacklisted":
                    continue
                ordered.append(c)

            search_type = "semantic"
            scores_by_idx: dict[int, float] = {
                i: qdrant_scores.get(c.id, 0.0) for i, c in enumerate(ordered)
            }

            if rerank_enabled and ordered:
                docs = [_build_candidate_text(c)[:4000] for c in ordered]
                # Rerank the whole pool (top_k=len(docs)) so threshold filtering
                # below sees a fully-ranked list, not a pre-trimmed one.
                pairs = await rerank_or_passthrough(query_text, docs, top_k=len(docs))
                if pairs and any(score != 1.0 for _, score in pairs):
                    # Real rerank result (passthrough returns score=1.0 for all).
                    # Reorder per rerank, scores aligned to new positions.
                    search_type = "semantic+rerank"
                    ordered = [ordered[idx] for idx, _ in pairs]
                    scores_by_idx = {i: score for i, (_, score) in enumerate(pairs)}
                # Passthrough / failure → keep Qdrant order + scores as-is.

            matches = [
                _build_match_info(c, required_skills, score=scores_by_idx.get(i, 0.0))
                for i, c in enumerate(ordered)
            ]
            # Location filter (when active): keep only candidates whose location
            # matches the request, preserving the semantic ranking order.
            if location_active:
                matches = [
                    m
                    for m in matches
                    if _location_matches(requested_tokens, m["candidate"]["location"])
                ]
            # Threshold filter: show everyone who fits, capped for payload safety.
            matches = [m for m in matches if m["match_score"] >= threshold][
                :max_results
            ]

            return {
                "job_id": job_id,
                "job_title": job.title,
                "required_skills": required_skills,
                "search_type": search_type,
                "min_score": round(threshold, 3),
                "location_filter": requested_location if location_active else None,
                "matches": matches,
            }
    except Exception as e:
        logger.warning(
            f"[AIMatch] Qdrant search failed for job {job_id}: {e} — falling back to tag-based"
        )

    # ── Fallback: tag-based matching ─────────────────────────────────────────
    logger.info(f"[AIMatch] Using tag-based fallback for job {job_id}")

    # Grab all active candidates (bounded by the retrieval pool for performance)
    all_result = await db.execute(
        select(Candidate).where(Candidate.status != "blacklisted").limit(effective_pool)
    )
    all_candidates = all_result.scalars().all()

    matches = []
    for c in all_candidates:
        # Location filter (when active): skip non-matching candidates up front.
        if location_active and not _location_matches(requested_tokens, c.location):
            continue
        match = _build_match_info(c, required_skills, score=None)
        # No required_skills → score is a profile-completeness proxy; keep the
        # threshold floor so junk profiles don't surface as "matches".
        if match["match_score"] >= threshold:
            matches.append(match)

    # Sort by score desc, show all who clear the threshold (capped).
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    matches = matches[:max_results]

    return {
        "job_id": job_id,
        "job_title": job.title,
        "required_skills": required_skills,
        "search_type": "tag_fallback",
        "min_score": round(threshold, 3),
        "location_filter": requested_location if location_active else None,
        "matches": matches,
    }
