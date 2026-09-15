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
from typing import Iterable, Optional, Sequence, Union

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


def _competence_category_matches(job: Job, targets: Union[str, Sequence[str]]) -> bool:
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


async def load_active_conflicts_bulk(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> dict[int, dict[int, ConflictType]]:
    """Return ``{candidate_id: {client_id: ConflictType}}`` for a whole page.

    Active = `active=True` AND (`expires_at` is NULL OR `expires_at > now()`).

    One SELECT for any number of candidates. „Szukają projektu" filtrowało
    stronę 50 kandydatów, wołając `_load_active_conflicts` po kolei — 100
    zapytań na stronę, zanim w ogóle zaczął się scoring (UAT B06). Każdy
    przekazany kandydat jest w wyniku, także bez konfliktów (pusty słownik),
    więc „nie ma wpisu" nie myli się z „nie sprawdzono".

    Semantyka jest dokładnie ta sama co dawnej wersji dwuzapytaniowej: klient,
    dla którego istnieje choć jeden AKTYWNY wiersz po terminie, wypada ze
    słownika, a przy kilku aktywnych wierszach tego samego klienta wygrywa
    ostatni (teraz jawnie: po `id`, zamiast w nieokreślonej kolejności).
    """
    ids = sorted({int(cid) for cid in candidate_ids if cid is not None})
    out: dict[int, dict[int, ConflictType]] = {cid: {} for cid in ids}
    if not ids:
        return out
    now = datetime.now(timezone.utc)
    rows = (
        await db.execute(
            select(
                CandidateConflict.candidate_id,
                CandidateConflict.client_id,
                CandidateConflict.type,
                CandidateConflict.expires_at,
            )
            .where(
                CandidateConflict.candidate_id.in_(ids),
                CandidateConflict.active.is_(True),
            )
            .order_by(CandidateConflict.id)
        )
    ).all()

    expired: set[tuple[int, int]] = set()
    for cand_id, client_id, ctype, expires_at in rows:
        out[cand_id][client_id] = ctype
        if expires_at is not None and expires_at <= now:
            expired.add((cand_id, client_id))
    for cand_id, client_id in expired:
        out[cand_id].pop(client_id, None)
    return out


async def _load_active_conflicts(
    db: AsyncSession, candidate_id: int
) -> dict[int, ConflictType]:
    """Return {client_id: ConflictType} for the candidate's active, unexpired conflicts."""
    return (await load_active_conflicts_bulk(db, [candidate_id]))[candidate_id]


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
    *,
    conflicts: Optional[dict[int, ConflictType]] = None,
) -> tuple[list[FilteredJob], FilterStats]:
    """Filter `jobs` for `candidate` according to `filters`.

    Returns `(kept, stats)`. The same job may carry a non-`None` `warning`
    when soft-flagged (e.g. `current_employment`). Hard drops never appear in
    `kept`.

    Hard conflicts (blacklist/competitor/nda) are ALWAYS loaded and enforced —
    `filters.industry_blocklist=False` only suppresses the soft
    `current_employment` warning annotation, never the hard exclusion set.

    ``conflicts`` lets a batch caller pass the set it already loaded for the
    whole page (`load_active_conflicts_bulk`) — it must be the COMPLETE active
    set for this candidate, never a subset, or a hard conflict would slip
    through. ``None`` keeps the per-candidate lookup.
    """
    # Ephemeral candidates (CV-preview, no DB row) have id=None — nothing to
    # look up. Every persisted candidate gets the full fail-closed hard set.
    if candidate.id is None:
        conflicts = {}
    elif conflicts is None:
        conflicts = await _load_active_conflicts(db, candidate.id)
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
