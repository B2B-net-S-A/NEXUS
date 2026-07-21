"""Match score cache service (Phase C1).

Read-through cache for `scoring_service.score_candidate_job`. Saves recompute
work on hot endpoints like `/jobs/{id}/recommendations`.

Contract
--------
- `get_cached_or_compute` returns a ScoreBreakdown for one (candidate, job)
  pair, using the cache when fresh.
- `bulk_get_or_compute` takes a list of candidates (+ optional similarity map)
  and returns a list of ScoreBreakdowns, minimizing recompute. This is what the
  recommendations endpoint will use.
- `mark_stale_for_candidate(candidate_id)` and `mark_stale_for_job(job_id)` are
  called on entity edits so the next read recomputes.

Fresh-vs-stale decision
-----------------------
A row is considered fresh iff `stale == False`. We do NOT use TTL — explicit
invalidation is safer (avoids surprise recomputes and churn). The background
worker (future) can sweep `stale=True` rows and refresh them in batch.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    SCORING_ALGORITHM_VERSION,
    LayerResult,
    ScoreBreakdown,
    WeightProfile,
    score_candidate_job,
)

logger = logging.getLogger(__name__)


# ── Cache round-trip ──────────────────────────────────────────────────────────


def _breakdown_from_row(row: CandidateJobMatchScore) -> ScoreBreakdown:
    """Hydrate a ScoreBreakdown dataclass from a persisted row."""
    b = row.breakdown or {}

    def layer(key: str) -> LayerResult:
        d = b.get(key, {}) or {}
        return LayerResult(
            points=float(d.get("points", 0.0)),
            max_points=float(d.get("max", 0.0)),
            reason=str(d.get("reason", "") or ""),
        )

    return ScoreBreakdown(
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        total=float(row.total_score),
        semantic=layer("semantic"),
        skills=layer("skills"),
        salary=layer("salary"),
        location=layer("location"),
        availability=layer("availability"),
        champion_fit=layer("champion_fit"),
        matching_must=list(b.get("matching_must") or []),
        gap_must=list(b.get("gap_must") or []),
        matching_nice=list(b.get("matching_nice") or []),
        gap_nice=list(b.get("gap_nice") or []),
        penalties=list(b.get("penalties") or []),
        fit_confidence=b.get("fit_confidence"),
    )


async def _upsert_breakdown(
    db: AsyncSession,
    breakdown: ScoreBreakdown,
    *,
    profile_id: int,
    compute_start: datetime,
) -> None:
    """Persist (insert-or-update) a computed breakdown; conditionally clears `stale`.

    CAS fence (P1-MATCH-02): a compute that STARTED before a concurrent
    ``mark_stale_*`` must never resurrect a fresh cache row. ``compute_start`` is
    the DB clock captured *before* scoring began; ``mark_stale_*`` stamps
    ``invalidated_at`` with the DB clock. On conflict we clear ``stale`` only when
    the row was NOT invalidated after this compute began
    (``invalidated_at IS NULL OR invalidated_at < compute_start``); otherwise
    ``stale`` stays ``True`` so the next read recomputes against the newer data.
    The freshly computed breakdown is still written either way — only the staleness
    verdict is gated.
    """
    stmt = pg_insert(CandidateJobMatchScore).values(
        candidate_id=breakdown.candidate_id,
        job_id=breakdown.job_id,
        profile_id=profile_id,
        total_score=breakdown.total,
        breakdown=breakdown.as_dict(),
        stale=False,
        scoring_algorithm_version=SCORING_ALGORITHM_VERSION,
    )
    # Unqualified column refs in an ON CONFLICT DO UPDATE SET/predicate resolve to
    # the EXISTING row, so this reads the invalidated_at written by any mark_stale
    # that landed while this compute was in flight.
    not_invalidated_mid_compute = or_(
        CandidateJobMatchScore.invalidated_at.is_(None),
        CandidateJobMatchScore.invalidated_at < compute_start,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            CandidateJobMatchScore.candidate_id,
            CandidateJobMatchScore.job_id,
            CandidateJobMatchScore.profile_id,
        ],
        set_={
            "total_score": stmt.excluded.total_score,
            "breakdown": stmt.excluded.breakdown,
            "scored_at": func.now(),
            "stale": case((not_invalidated_mid_compute, False), else_=True),
            "scoring_algorithm_version": SCORING_ALGORITHM_VERSION,
        },
    )
    await db.execute(stmt)


async def _persist_breakdowns(
    breakdowns: Sequence[ScoreBreakdown],
    *,
    profile_id: int,
    compute_start: datetime,
) -> None:
    """Write computed breakdowns to the cache on a DEDICATED session (M3-TX-01).

    The write-through cache is best-effort: persisting a freshly computed score
    must never commit or roll back the CALLER's request transaction. The caller
    owns its session via ``Depends(get_db)`` — a ``/recommendations`` read or a
    justification generation must not be finalized (or discarded) as a side
    effect of an unrelated cache write. Running the upsert on its own
    ``AsyncSessionLocal`` fully isolates any failure, mirroring
    :func:`index_outbox_service._default_reindex`.
    """
    if not breakdowns:
        return
    try:
        async with AsyncSessionLocal() as s:
            for b in breakdowns:
                await _upsert_breakdown(
                    s, b, profile_id=profile_id, compute_start=compute_start
                )
            await s.commit()
    except Exception as e:  # pragma: no cover — write-through best-effort
        logger.warning("match score cache upsert failed: %s", e)


# ── Public API ────────────────────────────────────────────────────────────────


async def get_cached_or_compute(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    *,
    semantic_similarity: Optional[float] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
    allow_cache_write: bool = True,
) -> ScoreBreakdown:
    """
    Return a fresh ScoreBreakdown: hit the cache first, recompute on miss/stale.

    The cache is keyed by (candidate, job, profile) so different weight
    profiles don't trample each other's results.

    ``allow_cache_write=False`` — degraded mode (M3-CACHE-01), mirroring
    :func:`bulk_get_or_compute`: the caller computed with a neutral semantic
    layer because Qdrant/Voyage were down, so the result is still returned for
    display but must NOT be persisted as a fresh cache row — otherwise the wrong
    score outlives the outage. Cache READS stay allowed (prior good rows are OK).
    """
    row = await db.scalar(
        select(CandidateJobMatchScore).where(
            CandidateJobMatchScore.candidate_id == candidate.id,
            CandidateJobMatchScore.job_id == job.id,
            CandidateJobMatchScore.profile_id == profile.id,
        )
    )
    if (
        row is not None
        and not row.stale
        and row.scoring_algorithm_version == SCORING_ALGORITHM_VERSION
    ):
        return _breakdown_from_row(row)

    # Fence the write-back against invalidations that land while we compute
    # (P1-MATCH-02): capture the DB clock BEFORE scoring starts.
    compute_start = await db.scalar(select(func.now()))
    breakdown = await score_candidate_job(
        candidate, job, db, semantic_similarity=semantic_similarity, profile=profile
    )
    if allow_cache_write:
        await _persist_breakdowns(
            [breakdown], profile_id=profile.id, compute_start=compute_start
        )
    return breakdown


async def bulk_get_or_compute(
    job: Job,
    candidates: Sequence[Candidate],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
    allow_cache_write: bool = True,
) -> list[ScoreBreakdown]:
    """Score N candidates against one job, preferring cache, sorted desc by total.

    ``allow_cache_write=False`` — degraded-retrieval mode (M3-CACHE-01): the
    caller had no Qdrant similarities, so freshly computed composites carry a
    neutral semantic layer. They are still returned for display, but must NOT
    be persisted as fresh cache rows, or the wrong scores would outlive the
    provider outage. Cache READS remain allowed (previous good rows are fine).
    """
    if not candidates:
        return []

    sims = similarity_map or {}
    cached_rows = (
        (
            await db.execute(
                select(CandidateJobMatchScore).where(
                    CandidateJobMatchScore.job_id == job.id,
                    CandidateJobMatchScore.candidate_id.in_([c.id for c in candidates]),
                    CandidateJobMatchScore.profile_id == profile.id,
                    CandidateJobMatchScore.stale.is_(False),
                    CandidateJobMatchScore.scoring_algorithm_version
                    == SCORING_ALGORITHM_VERSION,
                )
            )
        )
        .scalars()
        .all()
    )
    cached_by_cid = {r.candidate_id: r for r in cached_rows}

    # Fence the write-back against invalidations that land while we compute
    # (P1-MATCH-02): one DB-clock read BEFORE any scoring, only when we will
    # actually compute at least one miss.
    needs_compute = any(c.id not in cached_by_cid for c in candidates)
    compute_start = await db.scalar(select(func.now())) if needs_compute else None

    results: list[ScoreBreakdown] = []
    pending_writes: list[ScoreBreakdown] = []
    for c in candidates:
        row = cached_by_cid.get(c.id)
        if row is not None:
            results.append(_breakdown_from_row(row))
            continue
        breakdown = await score_candidate_job(
            c, job, db, semantic_similarity=sims.get(c.id), profile=profile
        )
        results.append(breakdown)
        pending_writes.append(breakdown)

    if pending_writes and allow_cache_write and compute_start is not None:
        await _persist_breakdowns(
            pending_writes, profile_id=profile.id, compute_start=compute_start
        )

    results.sort(key=lambda r: -r.total)
    return results


async def mark_stale_for_candidate(db: AsyncSession, candidate_id: int) -> int:
    """Mark all (candidate, *) cached rows stale. Returns row count affected."""
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.candidate_id == candidate_id)
        .values(stale=True, invalidated_at=func.now())
    )
    return res.rowcount or 0


async def mark_stale_for_job(db: AsyncSession, job_id: int) -> int:
    """Mark all (*, job) cached rows stale. Returns row count affected."""
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.job_id == job_id)
        .values(stale=True, invalidated_at=func.now())
    )
    return res.rowcount or 0


async def mark_stale_for_profile(db: AsyncSession, profile_id: int) -> int:
    """Mark all (*, *, profile) cached rows stale — call when a weight profile's
    weights change or the profile is deleted (AI-P0-06 part a).

    The cache key is (candidate, job, profile) + a global algorithm-version
    string, but that string tracks only the scoring contract + embedding model,
    NOT per-profile weights. So editing a profile's weights in place would keep
    serving old-weight scores under the same profile_id. Invalidating by
    profile_id closes that. Caller owns the transaction (no commit here).
    """
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.profile_id == profile_id)
        .values(stale=True, invalidated_at=func.now())
    )
    return res.rowcount or 0


async def mark_stale_for_many_candidates(
    db: AsyncSession, candidate_ids: Iterable[int]
) -> int:
    """Batch helper for bulk edits."""
    ids = list(candidate_ids)
    if not ids:
        return 0
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.candidate_id.in_(ids))
        .values(stale=True, invalidated_at=func.now())
    )
    return res.rowcount or 0
