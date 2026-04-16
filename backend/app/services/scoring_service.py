"""
Hybrid candidate-job scoring engine (Phase 2).

Layered scoring — each layer returns points that add up to 100:

  semantic        0-40pt   Qdrant cosine similarity between job query and candidate embedding
  skills          0-30pt   weighted must/nice overlap (must=20pt, nice=10pt)
  salary_fit      0-15pt   candidate rate fits inside job salary_min..salary_max
  location_fit    0-10pt   remote/hybrid compat + country + city bonus
  availability    0-5pt    candidate availability_date before/at job deadline

Penalties zero the score:
  blacklist            -100  Candidate.status == blacklisted
  active_conflict      -100  CandidateConflict.active == True for this (candidate, client)
  client_excluded      -100  client_id in Candidate.preferences.excluded_clients

Explainable: every call returns a ScoreBreakdown with per-layer points, matched/gap
lists, and active penalties so the UI can render a "why" tooltip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_conflict import CandidateConflict
from app.models.job import Job

logger = logging.getLogger(__name__)


# ── Point budgets ────────────────────────────────────────────────────────────

SEMANTIC_MAX = 40.0
SKILLS_MAX = 30.0  # must=20, nice=10
SKILLS_MUST_MAX = 20.0
SKILLS_NICE_MAX = 10.0
SALARY_MAX = 15.0
LOCATION_MAX = 10.0
AVAILABILITY_MAX = 5.0


# ── Data classes ────────────────────────────────────────────────────────────


@dataclass
class LayerResult:
    points: float
    max_points: float
    reason: str = ""


@dataclass
class ScoreBreakdown:
    candidate_id: int
    job_id: int
    total: float  # 0-100
    semantic: LayerResult
    skills: LayerResult
    salary: LayerResult
    location: LayerResult
    availability: LayerResult
    matching_must: List[str] = field(default_factory=list)
    gap_must: List[str] = field(default_factory=list)
    matching_nice: List[str] = field(default_factory=list)
    gap_nice: List[str] = field(default_factory=list)
    penalties: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "job_id": self.job_id,
            "total": round(self.total, 1),
            "semantic": {
                "points": round(self.semantic.points, 1),
                "max": self.semantic.max_points,
                "reason": self.semantic.reason,
            },
            "skills": {
                "points": round(self.skills.points, 1),
                "max": self.skills.max_points,
                "reason": self.skills.reason,
            },
            "salary": {
                "points": round(self.salary.points, 1),
                "max": self.salary.max_points,
                "reason": self.salary.reason,
            },
            "location": {
                "points": round(self.location.points, 1),
                "max": self.location.max_points,
                "reason": self.location.reason,
            },
            "availability": {
                "points": round(self.availability.points, 1),
                "max": self.availability.max_points,
                "reason": self.availability.reason,
            },
            "matching_must": self.matching_must,
            "gap_must": self.gap_must,
            "matching_nice": self.matching_nice,
            "gap_nice": self.gap_nice,
            "penalties": self.penalties,
        }


# ── Helpers ──────────────────────────────────────────────────────────────────


def _skill_names(raw) -> List[str]:
    """Extract lowercase skill names from JSONB (list of dict/str)."""
    out: List[str] = []
    if not raw:
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.append(str(name).lower().strip())
            elif isinstance(item, str):
                out.append(item.lower().strip())
    return [s for s in out if s]


def _score_skills(
    candidate: Candidate, job: Job
) -> tuple[LayerResult, List[str], List[str], List[str], List[str]]:
    """Return (LayerResult, matching_must, gap_must, matching_nice, gap_nice)."""
    must = _skill_names(job.must_skills)
    nice = _skill_names(job.nice_skills)
    cand_skills = set(
        _skill_names(candidate.skills) + _skill_names(candidate.verified_tech)
    )
    # Tags fallback
    if not cand_skills and candidate.tags:
        cand_skills = set(_skill_names(candidate.tags))

    must_match = [s for s in must if s in cand_skills]
    must_gap = [s for s in must if s not in cand_skills]
    nice_match = [s for s in nice if s in cand_skills]
    nice_gap = [s for s in nice if s not in cand_skills]

    must_pts = (
        (len(must_match) / len(must) * SKILLS_MUST_MAX) if must else SKILLS_MUST_MAX
    )
    nice_pts = (len(nice_match) / len(nice) * SKILLS_NICE_MAX) if nice else 0.0

    total = must_pts + nice_pts
    reason_bits = []
    if must:
        reason_bits.append(f"must {len(must_match)}/{len(must)}")
    else:
        reason_bits.append("must n/a")
    if nice:
        reason_bits.append(f"nice {len(nice_match)}/{len(nice)}")

    return (
        LayerResult(points=total, max_points=SKILLS_MAX, reason=", ".join(reason_bits)),
        must_match,
        must_gap,
        nice_match,
        nice_gap,
    )


def _score_salary(candidate: Candidate, job: Job) -> LayerResult:
    """15pt if in range, linear decay outside. 0 if missing data."""
    cand_rate = candidate.salary_expectation
    job_min = job.salary_min
    job_max = job.salary_max

    # Prefer structured preferences.rate_min/rate_max if available
    prefs = getattr(candidate, "preferences", None) or {}
    if isinstance(prefs, dict):
        cand_rate = prefs.get("rate_min") or cand_rate or prefs.get("rate_max")

    if not cand_rate or (not job_min and not job_max):
        return LayerResult(points=0.0, max_points=SALARY_MAX, reason="brak danych")

    # Inside range → full points
    if (job_min is None or cand_rate >= job_min) and (
        job_max is None or cand_rate <= job_max
    ):
        return LayerResult(
            points=SALARY_MAX, max_points=SALARY_MAX, reason="w widełkach"
        )

    # Outside: linear decay within ±30% of nearest bound
    if job_max and cand_rate > job_max:
        over = cand_rate - job_max
        decay = max(0.0, 1.0 - (over / (job_max * 0.3)))
        pts = SALARY_MAX * decay
        return LayerResult(
            points=pts,
            max_points=SALARY_MAX,
            reason=f"powyżej widełek o {over} PLN",
        )
    if job_min and cand_rate < job_min:
        under = job_min - cand_rate
        decay = max(0.0, 1.0 - (under / (job_min * 0.3)))
        pts = SALARY_MAX * decay
        return LayerResult(
            points=pts,
            max_points=SALARY_MAX,
            reason=f"poniżej widełek o {under} PLN",
        )

    return LayerResult(points=0.0, max_points=SALARY_MAX, reason="poza widełkami")


def _score_location(candidate: Candidate, job: Job) -> LayerResult:
    """Remote+country match = 10pt. Country match = 6pt. No match = 0."""
    points = 0.0
    reason_bits: List[str] = []

    # Remote policy compatibility
    prefs = getattr(candidate, "preferences", None) or {}
    remote_modes = prefs.get("remote_modes") if isinstance(prefs, dict) else None
    job_remote = job.remote_policy.value if job.remote_policy else None
    if remote_modes and job_remote and job_remote in remote_modes:
        points += 5.0
        reason_bits.append(f"remote {job_remote} OK")

    # Location substring match
    cand_loc = (candidate.location or "").lower()
    job_loc = (job.location or "").lower()
    if cand_loc and job_loc:
        if cand_loc in job_loc or job_loc in cand_loc:
            points += 5.0
            reason_bits.append("lokalizacja OK")
        # Partial: same first word (city/country prefix)
        elif cand_loc.split(",")[0].strip() == job_loc.split(",")[0].strip():
            points += 3.0
            reason_bits.append("to samo miasto")

    return LayerResult(
        points=min(points, LOCATION_MAX),
        max_points=LOCATION_MAX,
        reason=", ".join(reason_bits) or "brak dopasowania",
    )


def _score_availability(candidate: Candidate, job: Job) -> LayerResult:
    """5pt if available before/at job deadline. Linear decay over 30 days late."""
    if not candidate.availability_date:
        return LayerResult(
            points=AVAILABILITY_MAX * 0.5,
            max_points=AVAILABILITY_MAX,
            reason="brak daty",
        )
    if not job.deadline:
        return LayerResult(
            points=AVAILABILITY_MAX, max_points=AVAILABILITY_MAX, reason="brak deadline"
        )

    delta_days = (candidate.availability_date - job.deadline).days
    if delta_days <= 0:
        return LayerResult(
            points=AVAILABILITY_MAX, max_points=AVAILABILITY_MAX, reason="na czas"
        )

    decay = max(0.0, 1.0 - delta_days / 30.0)
    return LayerResult(
        points=AVAILABILITY_MAX * decay,
        max_points=AVAILABILITY_MAX,
        reason=f"spóźnienie {delta_days} dni",
    )


async def _check_penalties(
    candidate: Candidate, job: Job, db: AsyncSession
) -> List[str]:
    penalties: List[str] = []

    if candidate.status == CandidateStatus.blacklisted:
        penalties.append("blacklist")

    # Preferences.excluded_clients
    prefs = getattr(candidate, "preferences", None) or {}
    if isinstance(prefs, dict):
        excluded = prefs.get("excluded_clients") or []
        if job.client_id and job.client_id in excluded:
            penalties.append("client_excluded")

    # Active conflict for this (candidate, client)
    if job.client_id:
        active_conflict = await db.scalar(
            select(CandidateConflict.id).where(
                CandidateConflict.candidate_id == candidate.id,
                CandidateConflict.client_id == job.client_id,
                CandidateConflict.active.is_(True),
            )
        )
        if active_conflict:
            penalties.append("active_conflict")

    return penalties


# ── Public API ──────────────────────────────────────────────────────────────


def score_semantic(semantic_similarity: Optional[float]) -> LayerResult:
    """Convert Qdrant cosine similarity (0-1) → 0-40pt."""
    if semantic_similarity is None:
        return LayerResult(
            points=0.0, max_points=SEMANTIC_MAX, reason="brak embeddingu"
        )
    sim = max(0.0, min(1.0, float(semantic_similarity)))
    return LayerResult(
        points=sim * SEMANTIC_MAX,
        max_points=SEMANTIC_MAX,
        reason=f"sim {sim:.2f}",
    )


async def score_candidate_job(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    *,
    semantic_similarity: Optional[float] = None,
) -> ScoreBreakdown:
    """Compute the full ScoreBreakdown for one (candidate, job) pair."""
    import time as _time

    t0 = _time.perf_counter()
    semantic = score_semantic(semantic_similarity)
    skills, must_match, must_gap, nice_match, nice_gap = _score_skills(candidate, job)
    salary = _score_salary(candidate, job)
    location = _score_location(candidate, job)
    availability = _score_availability(candidate, job)
    penalties = await _check_penalties(candidate, job, db)

    if penalties:
        total = 0.0
    else:
        total = (
            semantic.points
            + skills.points
            + salary.points
            + location.points
            + availability.points
        )

    latency_ms = round((_time.perf_counter() - t0) * 1000.0, 2)
    # Structured event for log aggregation (JSON formatter reshapes extras)
    logger.info(
        "score_computed",
        extra={
            "event": "score_computed",
            "candidate_id": candidate.id,
            "job_id": job.id,
            "total_score": round(total, 2),
            "semantic_points": round(semantic.points, 2),
            "skills_points": round(skills.points, 2),
            "salary_points": round(salary.points, 2),
            "location_points": round(location.points, 2),
            "availability_points": round(availability.points, 2),
            "penalties_count": len(penalties),
            "must_matched": len(must_match),
            "must_missing": len(must_gap),
            "latency_ms": latency_ms,
        },
    )

    return ScoreBreakdown(
        candidate_id=candidate.id,
        job_id=job.id,
        total=total,
        semantic=semantic,
        skills=skills,
        salary=salary,
        location=location,
        availability=availability,
        matching_must=must_match,
        gap_must=must_gap,
        matching_nice=nice_match,
        gap_nice=nice_gap,
        penalties=penalties,
    )


async def rank_candidates_for_job(
    job: Job,
    candidates: Sequence[Candidate],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
) -> List[ScoreBreakdown]:
    """Convenience: score each candidate and return list sorted by total desc."""
    sims = similarity_map or {}
    results: List[ScoreBreakdown] = []
    for c in candidates:
        sim = sims.get(c.id)
        results.append(await score_candidate_job(c, job, db, semantic_similarity=sim))
    results.sort(key=lambda r: -r.total)
    return results


async def rank_jobs_for_candidate(
    candidate: Candidate,
    jobs: Iterable[Job],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
) -> List[ScoreBreakdown]:
    """Reverse direction — score each job for a given candidate."""
    sims = similarity_map or {}
    results: List[ScoreBreakdown] = []
    for j in jobs:
        sim = sims.get(j.id)
        results.append(
            await score_candidate_job(candidate, j, db, semantic_similarity=sim)
        )
    results.sort(key=lambda r: -r.total)
    return results
