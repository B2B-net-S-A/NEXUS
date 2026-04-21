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
from app.models.candidate import Candidate
from app.models.job import Job

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
    top_k: int = 10,
    db: AsyncSession = Depends(get_db),
):
    """
    GET /api/jobs/{job_id}/ai-matches

    Returns top candidates matching the given job using Qdrant semantic search.
    Falls back to tag-based matching if Qdrant unavailable.
    """
    # Fetch job
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Oferta pracy nie istnieje")

    query_text = _build_job_query(job)
    required_skills = _parse_required_skills(job)

    # ── Attempt Qdrant semantic search ───────────────────────────────────────
    try:
        from app.services.embedding_service import search_candidates_semantic

        hits = await search_candidates_semantic(query_text, top_k=top_k * 2)

        if hits:
            candidate_ids = [h["candidate_id"] for h in hits[: top_k * 2]]
            score_map = {h["candidate_id"]: h["score"] for h in hits}

            cand_result = await db.execute(
                select(Candidate).where(Candidate.id.in_(candidate_ids))
            )
            candidates_by_id = {c.id: c for c in cand_result.scalars().all()}

            matches = []
            for cid in candidate_ids[: top_k * 2]:
                c = candidates_by_id.get(cid)
                if not c:
                    continue
                raw_score = score_map.get(cid, 0.0)
                match = _build_match_info(c, required_skills, score=raw_score)
                matches.append(match)

            # Sort by score desc, trim to top_k
            matches.sort(key=lambda x: x["match_score"], reverse=True)
            matches = matches[:top_k]

            return {
                "job_id": job_id,
                "job_title": job.title,
                "required_skills": required_skills,
                "search_type": "semantic",
                "matches": matches,
            }
    except Exception as e:
        logger.warning(
            f"[AIMatch] Qdrant search failed for job {job_id}: {e} — falling back to tag-based"
        )

    # ── Fallback: tag-based matching ─────────────────────────────────────────
    logger.info(f"[AIMatch] Using tag-based fallback for job {job_id}")

    # Grab all active candidates (limited to 200 for performance)
    all_result = await db.execute(
        select(Candidate).where(Candidate.status != "blacklisted").limit(200)
    )
    all_candidates = all_result.scalars().all()

    matches = []
    for c in all_candidates:
        match = _build_match_info(c, required_skills, score=None)
        if match["match_score"] > 0 or not required_skills:
            matches.append(match)

    # Sort by score desc, take top_k
    matches.sort(key=lambda x: x["match_score"], reverse=True)
    matches = matches[:top_k]

    return {
        "job_id": job_id,
        "job_title": job.title,
        "required_skills": required_skills,
        "search_type": "tag_fallback",
        "matches": matches,
    }
