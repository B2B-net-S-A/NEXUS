"""Post-filter for hybrid scoring recommendations.

Pure functions applied AFTER `scoring_service.rank_jobs_for_candidate` (or its
inverse) ranks matches:

- Hard filters on user-overridable criteria (location, salary ±tolerance,
  availability, competence_category)
- Industry blocklist via `CandidateConflict`:
    - `blacklist` + `competitor`           → hard drop (ALWAYS — fail-closed)
    - `nda` (with active `expires_at`)     → hard drop (ALWAYS — fail-closed)
    - `current_employment`                  → soft warn (annotated, not removed)

M2 audit PR 1 (M2-SEC-03): hard NDA/blacklist/competitor exclusions are
enforced server-side regardless of caller input. `filters.industry_blocklist`
used to skip loading conflicts entirely — any logged-in user could surface
hard-blocked jobs by passing `industry_blocklist=false`. The flag now only
toggles SOFT warnings (`current_employment` annotation); the hard set is
always applied and there is no parameter that bypasses it.

Separation of concerns: `scoring_service` stays untouched. This layer wraps
the result list and works in either direction (candidate→jobs or job→candidates)
because we always pass the candidate + the list of jobs being scored.

The filters are intentionally additive: each predicate returns True iff the
match should KEEP. Predicates compose via `_apply_all`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import AvailabilityStatus, Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.job import Job

logger = logging.getLogger(__name__)


# ── Public dataclasses ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class RecommendationFilters:
    """User-overridable filters applied after hybrid scoring.

    All fields default to `None`/permissive so an empty `RecommendationFilters()`
    is a no-op except for `industry_blocklist=True` which still respects
    `CandidateConflict` rows (the safe default for production).
    """

    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    salary_tolerance: float = 0.20  # ±20%
    availability: Optional[Sequence[AvailabilityStatus]] = None
    competence_category: Optional[Sequence[str]] = None
    # SOFT-warnings toggle only. Hard NDA/blacklist/competitor conflicts are
    # enforced unconditionally in `apply_user_filters` — this flag cannot
    # re-include a hard-blocked job (M2-SEC-03 fail-closed contract).
    industry_blocklist: bool = True


@dataclass
class FilteredJob:
    """One job after filtering — carries the original Job + an optional warning."""

    job: Job
    warning: Optional[str] = None


@dataclass(frozen=True)
class FilterStats:
    """Bookkeeping for caller diagnostics — not returned to the user UI."""

    initial: int = 0
    kept: int = 0
    dropped_location: int = 0
    dropped_salary: int = 0
    dropped_blocklist: int = 0
    soft_warned: int = 0


# ── Predicates (pure, single-direction) ─────────────────────────────────────


def _location_matches(job: Job, target: str) -> bool:
    """Loose location match — accepts city in either direction (substring)."""
    job_loc = (job.location or "").lower().strip()
    needle = target.lower().strip()
    if not job_loc or not needle:
        return True  # don't drop when either side is unknown
    if needle in job_loc or job_loc in needle:
        return True
    # Fall back to first-comma-segment compare ("Warszawa" in "Warszawa, PL")
    return job_loc.split(",")[0].strip() == needle.split(",")[0].strip()


def _salary_in_window(
    job: Job,
    user_min: Optional[int],
    user_max: Optional[int],
    tolerance: float,
) -> bool:
    """User salary range vs. job range with ±tolerance applied to job bounds.

    The check passes iff the two ranges overlap. Missing data → permissive
    (we don't drop a job for lack of salary data; scoring already penalizes it).
    """
    if user_min is None and user_max is None:
        return True
    j_min = job.salary_min
    j_max = job.salary_max
    if j_min is None and j_max is None:
        return True
    # Apply tolerance to job bounds
    pad_lo = int((j_min or 0) * (1.0 - tolerance)) if j_min is not None else None
    pad_hi = int((j_max or 0) * (1.0 + tolerance)) if j_max is not None else None
    # Overlap test
    if user_max is not None and pad_lo is not None and user_max < pad_lo:
        return False
    if user_min is not None and pad_hi is not None and user_min > pad_hi:
        return False
    return True


def _competence_category_matches(job: Job, targets: Sequence[str]) -> bool:
    """Match job against any of the target categories (OR-combined, case-insensitive).

    Each target is matched against job.subcategory / job.industry / job.title.
    Empty `targets` (or empty strings only) → True (no filter).

    A bare string counts as ONE category. `Sequence[str]` also matches `str`,
    whose elements are single CHARACTERS — so `targets="frontend"` would search
    for 'f', 'r', 'o', … and `any()` would fire on almost any job title. That is
    not a crash but a plausible-looking wrong answer, which is why it went
    unnoticed: it made `("Backend Engineer", "frontend")` match. Normalising
    here means the obvious reading of the call is also the correct one.
    """
    if isinstance(targets, str):
        targets = [targets]
    needles = [t.lower().strip() for t in targets if t and t.strip()]
    if not needles:
        return True
    job_fields = [
        getattr(job, "subcategory", None),
        getattr(job, "industry", None),
        job.title or "",
    ]
    haystack = " ".join((c or "").lower() for c in job_fields if c)
    return any(needle in haystack for needle in needles)


# ── Conflict resolution (industry blocklist) ────────────────────────────────


async def _load_active_conflicts(
    db: AsyncSession, candidate_id: int
) -> dict[int, ConflictType]:
    """Return {client_id: ConflictType} for the candidate's active, unexpired conflicts.

    Active = `active=True` AND (`expires_at` is NULL OR `expires_at > now()`).
    """
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(CandidateConflict.client_id, CandidateConflict.type).where(
                CandidateConflict.candidate_id == candidate_id,
                CandidateConflict.active.is_(True),
            )
        )
    ).all()

    out: dict[int, ConflictType] = {}
    for client_id, ctype in rows:
        # `expires_at` filtered in Python because rows is a small per-candidate set.
        out[client_id] = ctype
    # Re-query to also drop those expired (small list, two-pass keeps the SQL simple)
    expired_rows = (
        await db.execute(
            select(CandidateConflict.client_id).where(
                CandidateConflict.candidate_id == candidate_id,
                CandidateConflict.active.is_(True),
                CandidateConflict.expires_at.is_not(None),
                CandidateConflict.expires_at <= now,
            )
        )
    ).all()
    for (cid,) in expired_rows:
        out.pop(cid, None)
    return out


def _conflict_decision(
    job: Job, conflicts: dict[int, ConflictType]
) -> tuple[bool, Optional[str]]:
    """Return (keep, warning).

    - blacklist + competitor + nda → keep=False (hard drop)
    - current_employment           → keep=True, warning="obecnie u tego klienta"
    - no conflict                  → keep=True, warning=None
    """
    if not job.client_id:
        return True, None
    ctype = conflicts.get(job.client_id)
    if ctype is None:
        return True, None
    if ctype in (ConflictType.blacklist, ConflictType.competitor, ConflictType.nda):
        return False, None
    if ctype == ConflictType.current_employment:
        return True, "obecnie u tego klienta"
    return True, None


# ── Public API ──────────────────────────────────────────────────────────────


async def apply_user_filters(
    candidate: Candidate,
    jobs: Iterable[Job],
    filters: RecommendationFilters,
    db: AsyncSession,
) -> tuple[list[FilteredJob], FilterStats]:
    """Filter `jobs` for `candidate` according to `filters`.

    Returns `(kept, stats)`. The same job may carry a non-`None` `warning`
    when soft-flagged (e.g. `current_employment`). Hard drops never appear in
    `kept`.

    Hard conflicts (blacklist/competitor/nda) are ALWAYS loaded and enforced —
    `filters.industry_blocklist=False` only suppresses the soft
    `current_employment` warning annotation, never the hard exclusion set.
    """
    # Ephemeral candidates (CV-preview, no DB row) have id=None — nothing to
    # look up. Every persisted candidate gets the full fail-closed hard set.
    conflicts = (
        await _load_active_conflicts(db, candidate.id)
        if candidate.id is not None
        else {}
    )
    initial = 0
    dropped_location = 0
    dropped_salary = 0
    dropped_blocklist = 0
    soft_warned = 0
    kept: list[FilteredJob] = []

    for j in jobs:
        initial += 1

        if filters.location and not _location_matches(j, filters.location):
            dropped_location += 1
            continue

        if filters.salary_min is not None or filters.salary_max is not None:
            if not _salary_in_window(
                j, filters.salary_min, filters.salary_max, filters.salary_tolerance
            ):
                dropped_salary += 1
                continue

        if filters.competence_category and not _competence_category_matches(
            j, list(filters.competence_category)
        ):
            # Treat as location-style soft criterion: drop without separate counter.
            continue

        warning: Optional[str] = None
        if conflicts:
            keep, warning = _conflict_decision(j, conflicts)
            if not keep:
                # Hard drop — fail-closed, independent of any caller flag.
                dropped_blocklist += 1
                continue
            if warning and not filters.industry_blocklist:
                # Soft warnings are the only thing the user toggle controls.
                warning = None
            if warning:
                soft_warned += 1

        kept.append(FilteredJob(job=j, warning=warning))

    stats = FilterStats(
        initial=initial,
        kept=len(kept),
        dropped_location=dropped_location,
        dropped_salary=dropped_salary,
        dropped_blocklist=dropped_blocklist,
        soft_warned=soft_warned,
    )
    return kept, stats


def matches_availability(
    candidate: Candidate,
    filters: RecommendationFilters,
) -> bool:
    """Top-level availability gate.

    Used by callers that decide whether to even rank jobs for this candidate
    (e.g. the seeking-contractors batch endpoint won't bother running the
    scoring engine on `not_looking` candidates when the user filters them out).
    """
    if not filters.availability:
        return True
    return candidate.availability_status in set(filters.availability)
