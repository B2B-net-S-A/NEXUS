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
import hashlib
from typing import Iterable, Optional, Sequence

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    LayerResult,
    ScoreBreakdown,
    WeightProfile,
    score_candidate_job,
)

logger = logging.getLogger(__name__)
SCORING_ALGORITHM_VERSION = "hybrid_score_v2"


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cache_identity(
    candidate: Candidate, job: Job, profile: WeightProfile
) -> dict[str, str | int]:
    from app.services.embedding_service import (
        _build_candidate_text,
        _build_job_text,
        candidate_collection_name,
        job_collection_name,
    )

    return {
        "profile_version": profile.version,
        "scoring_algorithm_version": SCORING_ALGORITHM_VERSION,
        "index_version": (f"{candidate_collection_name()}|{job_collection_name()}"),
        "candidate_source_hash": _hash_text(_build_candidate_text(candidate)),
        "job_source_hash": _hash_text(_build_job_text(job)),
    }


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
    )


async def _upsert_breakdown(
    db: AsyncSession,
    breakdown: ScoreBreakdown,
    *,
    profile_id: int,
    identity: dict[str, str | int],
) -> None:
    """Persist (insert-or-update) a computed breakdown; clears `stale`."""
    stmt = pg_insert(CandidateJobMatchScore).values(
        candidate_id=breakdown.candidate_id,
        job_id=breakdown.job_id,
        profile_id=profile_id,
        **identity,
        total_score=breakdown.total,
        breakdown=breakdown.as_dict(),
        stale=False,
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
            "profile_version": stmt.excluded.profile_version,
            "scoring_algorithm_version": stmt.excluded.scoring_algorithm_version,
            "index_version": stmt.excluded.index_version,
            "candidate_source_hash": stmt.excluded.candidate_source_hash,
            "job_source_hash": stmt.excluded.job_source_hash,
            "scored_at": __import__("sqlalchemy").func.now(),
            "stale": False,
        },
    )
    await db.execute(stmt)


# ── Public API ────────────────────────────────────────────────────────────────


async def get_cached_or_compute(
    candidate: Candidate,
    job: Job,
    db: AsyncSession,
    *,
    semantic_similarity: Optional[float] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> ScoreBreakdown:
    """
    Return a fresh ScoreBreakdown: hit the cache first, recompute on miss/stale.

    The cache is keyed by (candidate, job, profile) so different weight
    profiles don't trample each other's results.
    """
    identity = _cache_identity(candidate, job, profile)
    row = await db.scalar(
        select(CandidateJobMatchScore).where(
            CandidateJobMatchScore.candidate_id == candidate.id,
            CandidateJobMatchScore.job_id == job.id,
            CandidateJobMatchScore.profile_id == profile.id,
            CandidateJobMatchScore.profile_version == identity["profile_version"],
            CandidateJobMatchScore.scoring_algorithm_version
            == identity["scoring_algorithm_version"],
            CandidateJobMatchScore.index_version == identity["index_version"],
            CandidateJobMatchScore.candidate_source_hash
            == identity["candidate_source_hash"],
            CandidateJobMatchScore.job_source_hash == identity["job_source_hash"],
        )
    )
    if row is not None and not row.stale:
        return _breakdown_from_row(row)

    breakdown = await score_candidate_job(
        candidate, job, db, semantic_similarity=semantic_similarity, profile=profile
    )
    try:
        await _upsert_breakdown(db, breakdown, profile_id=profile.id, identity=identity)
        await db.commit()
    except Exception as e:  # pragma: no cover — write-through best-effort
        logger.warning("match score cache upsert failed: %s", e)
        await db.rollback()
    return breakdown


async def bulk_get_or_compute(
    job: Job,
    candidates: Sequence[Candidate],
    db: AsyncSession,
    *,
    similarity_map: Optional[dict[int, float]] = None,
    profile: WeightProfile = DEFAULT_PROFILE,
) -> list[ScoreBreakdown]:
    """Score N candidates against one job, preferring cache, sorted desc by total."""
    if not candidates:
        return []

    sims = similarity_map or {}
    identities = {c.id: _cache_identity(c, job, profile) for c in candidates}
    common = identities[candidates[0].id]
    cached_rows = (
        (
            await db.execute(
                select(CandidateJobMatchScore).where(
                    CandidateJobMatchScore.job_id == job.id,
                    CandidateJobMatchScore.candidate_id.in_([c.id for c in candidates]),
                    CandidateJobMatchScore.profile_id == profile.id,
                    CandidateJobMatchScore.profile_version == common["profile_version"],
                    CandidateJobMatchScore.scoring_algorithm_version
                    == common["scoring_algorithm_version"],
                    CandidateJobMatchScore.index_version == common["index_version"],
                    CandidateJobMatchScore.job_source_hash == common["job_source_hash"],
                    CandidateJobMatchScore.stale.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    cached_by_cid = {
        r.candidate_id: r
        for r in cached_rows
        if r.candidate_source_hash
        == identities[r.candidate_id]["candidate_source_hash"]
    }

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

    if pending_writes:
        try:
            for b in pending_writes:
                await _upsert_breakdown(
                    db,
                    b,
                    profile_id=profile.id,
                    identity=identities[b.candidate_id],
                )
            await db.commit()
        except Exception as e:  # pragma: no cover
            logger.warning("match score bulk cache upsert failed: %s", e)
            await db.rollback()

    results.sort(key=lambda r: -r.total)
    return results


async def mark_stale_for_candidate(db: AsyncSession, candidate_id: int) -> int:
    """Mark all (candidate, *) cached rows stale. Returns row count affected."""
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.candidate_id == candidate_id)
        .values(stale=True)
    )
    return res.rowcount or 0


async def mark_stale_for_job(db: AsyncSession, job_id: int) -> int:
    """Mark all (*, job) cached rows stale. Returns row count affected."""
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.job_id == job_id)
        .values(stale=True)
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
        .values(stale=True)
    )
    return res.rowcount or 0
