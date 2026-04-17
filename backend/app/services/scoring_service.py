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


# ── Point budgets (defaults; overridable by WeightProfile) ──────────────────

SEMANTIC_MAX = 40.0
SKILLS_MAX = 30.0  # must=20, nice=10
SKILLS_MUST_MAX = 20.0
SKILLS_NICE_MAX = 10.0
SALARY_MAX = 15.0
LOCATION_MAX = 10.0
AVAILABILITY_MAX = 5.0


@dataclass(frozen=True)
class WeightProfile:
    """Resolved layer budgets used by the scoring engine on a single pass.

    `skills` is split into must/nice with the classic 2:1 ratio. The caller
    (e.g. Phase D1 `scoring_weight_profiles` table) supplies the 5 aggregate
    weights; the engine expands them internally.
    """

    id: int = 0  # 0 = built-in default; real profiles use their DB id
    name: str = "default"
    semantic: float = SEMANTIC_MAX
    skills: float = SKILLS_MAX
    salary: float = SALARY_MAX
    location: float = LOCATION_MAX
    availability: float = AVAILABILITY_MAX

    @property
    def skills_must(self) -> float:
        return self.skills * (2.0 / 3.0) if self.skills else 0.0

    @property
    def skills_nice(self) -> float:
        return self.skills * (1.0 / 3.0) if self.skills else 0.0

    @classmethod
    def from_record(cls, record) -> "WeightProfile":
        """Build from a `ScoringWeightProfile` ORM row."""
        w = record.weights or {}
        return cls(
            id=record.id,
            name=record.name,
            semantic=float(w.get("semantic", SEMANTIC_MAX)),
            skills=float(w.get("skills", SKILLS_MAX)),
            salary=float(w.get("salary", SALARY_MAX)),
            location=float(w.get("location", LOCATION_MAX)),
            availability=float(w.get("availability", AVAILABILITY_MAX)),
        )


DEFAULT_PROFILE = WeightProfile()


async def resolve_active_profile(
    db,
    *,
    user_id: Optional[int] = None,
    client_id: Optional[int] = None,
) -> WeightProfile:
    """Pick the most specific active scoring weight profile.

    Precedence: user_id match → client_id match → global (user_id IS NULL AND
    client_id IS NULL) → built-in DEFAULT_PROFILE. Non-active profiles are
    ignored.
    """
    # Local import to avoid circular at module load
    from sqlalchemy import select as _select

    from app.models.scoring_weight_profile import ScoringWeightProfile

    async def _fetch(where) -> Optional[WeightProfile]:
        row = await db.scalar(
            _select(ScoringWeightProfile)
            .where(ScoringWeightProfile.active.is_(True))
            .where(where)
            .limit(1)
        )
        return WeightProfile.from_record(row) if row else None

    if user_id is not None:
        p = await _fetch(ScoringWeightProfile.user_id == user_id)
        if p is not None:
            return p
    if client_id is not None:
        p = await _fetch(ScoringWeightProfile.client_id == client_id)
        if p is not None:
            return p
    p = await _fetch(
        (ScoringWeightProfile.user_id.is_(None))
        & (ScoringWeightProfile.client_id.is_(None))
    )
    return p or DEFAULT_PROFILE


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


_DICT_SKILL_LIST_KEYS = ("technologies", "skills", "stack", "tech")


# ── Alias map (Phase B1 skill taxonomy) ──────────────────────────────────────
#
# Populated at application startup from the `skill_aliases` table; normalized
# lookup `alias (lower) -> canonical (lower)`. Empty by default so tests and
# offline tools work without a DB connection.

ALIAS_MAP: dict[str, str] = {}


def set_alias_map(mapping: dict[str, str]) -> None:
    """Replace the in-memory alias map atomically (called from FastAPI startup)."""
    ALIAS_MAP.clear()
    ALIAS_MAP.update({k.lower(): v.lower() for k, v in mapping.items()})


def canonical_skill_names(raw) -> List[str]:
    """
    Return skill names normalized through the alias map, order-preserving,
    deduplicated. When `ALIAS_MAP` is empty, behaves exactly like `_skill_names`.
    """
    names = _skill_names(raw)
    if not ALIAS_MAP:
        return names
    seen: set[str] = set()
    out: List[str] = []
    for n in names:
        canonical = ALIAS_MAP.get(n, n)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _skill_names(raw) -> List[str]:
    """Extract lowercase skill names from JSONB.

    Accepted shapes (seed data in the wild mixes them):
      - list[str]                                        -> ["Python", "Go"]
      - list[dict]                                       -> [{"name": "Python"}, ...]
      - dict with "name" key                             -> {"name": "Python"}
      - dict with a list-valued key in _DICT_SKILL_LIST_KEYS
                                                          -> {"technologies": [...]}
    Anything else yields [] (silent ignore, matches prior behavior for unknown types).
    """
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
    elif isinstance(raw, dict):
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.lower().strip())
        for key in _DICT_SKILL_LIST_KEYS:
            value = raw.get(key)
            if isinstance(value, list):
                out.extend(_skill_names(value))
    return [s for s in out if s]


def _score_skills(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> tuple[LayerResult, List[str], List[str], List[str], List[str]]:
    """Return (LayerResult, matching_must, gap_must, matching_nice, gap_nice)."""
    must = canonical_skill_names(job.must_skills)
    nice = canonical_skill_names(job.nice_skills)
    cand_skills = set(
        canonical_skill_names(candidate.skills)
        + canonical_skill_names(candidate.verified_tech)
    )
    # Tags fallback
    if not cand_skills and candidate.tags:
        cand_skills = set(canonical_skill_names(candidate.tags))

    must_match = [s for s in must if s in cand_skills]
    must_gap = [s for s in must if s not in cand_skills]
    nice_match = [s for s in nice if s in cand_skills]
    nice_gap = [s for s in nice if s not in cand_skills]

    must_max = profile.skills_must
    nice_max = profile.skills_nice
    must_pts = (len(must_match) / len(must) * must_max) if must else must_max
    nice_pts = (len(nice_match) / len(nice) * nice_max) if nice else 0.0

    total = must_pts + nice_pts
    reason_bits = []
    if must:
        reason_bits.append(f"must {len(must_match)}/{len(must)}")
    else:
        reason_bits.append("must n/a")
    if nice:
        reason_bits.append(f"nice {len(nice_match)}/{len(nice)}")

    return (
        LayerResult(
            points=total, max_points=profile.skills, reason=", ".join(reason_bits)
        ),
        must_match,
        must_gap,
        nice_match,
        nice_gap,
    )


def _score_salary(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Salary fit — full points in range, linear decay outside. 0 if missing data."""
    max_pts = profile.salary
    cand_rate = candidate.salary_expectation
    job_min = job.salary_min
    job_max = job.salary_max

    # Prefer structured preferences.rate_min/rate_max if available
    prefs = getattr(candidate, "preferences", None) or {}
    if isinstance(prefs, dict):
        cand_rate = prefs.get("rate_min") or cand_rate or prefs.get("rate_max")

    if not cand_rate or (not job_min and not job_max):
        return LayerResult(points=0.0, max_points=max_pts, reason="brak danych")

    # Inside range → full points
    if (job_min is None or cand_rate >= job_min) and (
        job_max is None or cand_rate <= job_max
    ):
        return LayerResult(points=max_pts, max_points=max_pts, reason="w widełkach")

    # Outside: linear decay within ±30% of nearest bound
    if job_max and cand_rate > job_max:
        over = cand_rate - job_max
        decay = max(0.0, 1.0 - (over / (job_max * 0.3)))
        pts = max_pts * decay
        return LayerResult(
            points=pts, max_points=max_pts, reason=f"powyżej widełek o {over} PLN"
        )
    if job_min and cand_rate < job_min:
        under = job_min - cand_rate
        decay = max(0.0, 1.0 - (under / (job_min * 0.3)))
        pts = max_pts * decay
        return LayerResult(
            points=pts, max_points=max_pts, reason=f"poniżej widełek o {under} PLN"
        )

    return LayerResult(points=0.0, max_points=max_pts, reason="poza widełkami")


def _score_location(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Remote/location fit. Scales split between remote compatibility and city match."""
    max_pts = profile.location
    points = 0.0
    reason_bits: List[str] = []

    # Split budget 50/50 between remote policy and location string match
    half = max_pts / 2.0

    prefs = getattr(candidate, "preferences", None) or {}
    remote_modes = prefs.get("remote_modes") if isinstance(prefs, dict) else None
    job_remote = job.remote_policy.value if job.remote_policy else None
    if remote_modes and job_remote and job_remote in remote_modes:
        points += half
        reason_bits.append(f"remote {job_remote} OK")

    cand_loc = (candidate.location or "").lower()
    job_loc = (job.location or "").lower()
    if cand_loc and job_loc:
        if cand_loc in job_loc or job_loc in cand_loc:
            points += half
            reason_bits.append("lokalizacja OK")
        elif cand_loc.split(",")[0].strip() == job_loc.split(",")[0].strip():
            points += half * 0.6
            reason_bits.append("to samo miasto")

    return LayerResult(
        points=min(points, max_pts),
        max_points=max_pts,
        reason=", ".join(reason_bits) or "brak dopasowania",
    )


def _score_availability(
    candidate: Candidate, job: Job, profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Availability fit. Full points before deadline, decay 30 days post."""
    max_pts = profile.availability
    if not candidate.availability_date:
        return LayerResult(points=max_pts * 0.5, max_points=max_pts, reason="brak daty")
    if not job.deadline:
        return LayerResult(points=max_pts, max_points=max_pts, reason="brak deadline")

    delta_days = (candidate.availability_date - job.deadline).days
    if delta_days <= 0:
        return LayerResult(points=max_pts, max_points=max_pts, reason="na czas")

    decay = max(0.0, 1.0 - delta_days / 30.0)
    return LayerResult(
        points=max_pts * decay,
        max_points=max_pts,
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


def score_semantic(
    semantic_similarity: Optional[float], profile: WeightProfile = DEFAULT_PROFILE
) -> LayerResult:
    """Convert Qdrant cosine similarity (0-1) → profile.semantic points."""
    max_pts = profile.semantic
    if semantic_similarity is None:
        return LayerResult(points=0.0, max_points=max_pts, reason="brak embeddingu")
    sim = max(0.0, min(1.0, float(semantic_similarity)))
    return LayerResult(
        points=sim * max_pts, max_points=max_pts, reason=f"sim {sim:.2f}"
    )


async def score_candidate_job(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    *,
    semantic_similarity: Optional[float] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> ScoreBreakdown:
    """Compute the full ScoreBreakdown for one (candidate, job) pair."""
    import time as _time

    t0 = _time.perf_counter()
    semantic = score_semantic(semantic_similarity, profile)
    skills, must_match, must_gap, nice_match, nice_gap = _score_skills(
        candidate, job, profile
    )
    salary = _score_salary(candidate, job, profile)
    location = _score_location(candidate, job, profile)
    availability = _score_availability(candidate, job, profile)
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
    profile: WeightProfile = DEFAULT_PROFILE,
) -> List[ScoreBreakdown]:
    """Convenience: score each candidate and return list sorted by total desc."""
    sims = similarity_map or {}
    results: List[ScoreBreakdown] = []
    for c in candidates:
        sim = sims.get(c.id)
        results.append(
            await score_candidate_job(
                c, job, db, semantic_similarity=sim, profile=profile
            )
        )
    results.sort(key=lambda r: -r.total)
    return results


def summarize_match_stats(
    breakdowns: Sequence[ScoreBreakdown],
    total_open: int,
    *,
    min_score: float = 50.0,
) -> dict:
    """
    Summarize a list of candidate↔job ScoreBreakdowns into badge-ready stats.

    Returned shape matches what the candidates list UI renders on a row:

        {
          "open_count": int,        # breakdowns with total >= min_score
          "total_open": int,        # open jobs considered (from caller)
          "top_score": float,       # highest total (0.0 when no breakdowns)
        }
    """
    if not breakdowns:
        return {"open_count": 0, "total_open": total_open, "top_score": 0.0}
    open_count = sum(1 for b in breakdowns if b.total >= min_score)
    top_score = max(b.total for b in breakdowns)
    return {
        "open_count": open_count,
        "total_open": total_open,
        "top_score": round(top_score, 1),
    }


async def rank_jobs_for_candidate(
    candidate: Candidate,
    jobs: Iterable[Job],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> List[ScoreBreakdown]:
    """Reverse direction — score each job for a given candidate."""
    sims = similarity_map or {}
    results: List[ScoreBreakdown] = []
    for j in jobs:
        sim = sims.get(j.id)
        results.append(
            await score_candidate_job(
                candidate, j, db, semantic_similarity=sim, profile=profile
            )
        )
    results.sort(key=lambda r: -r.total)
    return results
