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
A row is fresh iff `stale == False` AND it was written by the CURRENT scoring
algorithm (`scoring_algorithm_version()`). Both halves are mandatory and live in
exactly one place: `fresh_score_conditions()`. Build every query over
`CandidateJobMatchScore` from it — a hand-written WHERE that checks only `stale`
treats a version-obsolete row as usable, and the two failure modes differ per
call site: a read-only surface silently shows a score from the previous
algorithm, while a compute path excludes the row from its own recompute set and
then writes a semantic-less score back under the new version, permanently.

There is no TTL — explicit invalidation is safer (avoids surprise recomputes and
churn). The background worker (future) can sweep `stale=True` rows in batch.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Iterable, Optional, Sequence

from sqlalchemy import and_, case, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.models.match_score_invalidation import MatchScoreInvalidation
from app.services.scoring_service import (
    DEFAULT_PROFILE,
    build_job_scoring_context,
    scoring_algorithm_version,
    LayerResult,
    ScoreBreakdown,
    WeightProfile,
    score_candidate_job,
)

logger = logging.getLogger(__name__)


# ── Cache round-trip ──────────────────────────────────────────────────────────


def fresh_score_conditions(
    *,
    job_id: int,
    profile_id: int,
    candidate_ids: Optional[Sequence[int]] = None,
) -> list:
    """Kryteria „ten wiersz cache nadaje się do użycia". JEDNO miejsce.

    Świeżość ma DWIE połowy — nieunieważniony (``stale is False``) i policzony
    BIEŻĄCYM algorytmem. Pominięcie drugiej połowy nie objawia się błędem, tylko
    liczbą: wiersz sprzed bumpu wag przechodzi jako aktualny.

    Skutek zależy od tego, co robi wywołujący. Powierzchnia tylko-do-odczytu
    pokaże wynik poprzedniego algorytmu obok wyniku bieżącego i dwa ekrany będą
    się różnić dla tego samego kandydata. Ścieżka licząca zrobi gorzej: wyłączy
    wiersz z własnego zbioru „do przeliczenia", więc nie pobierze dla niego
    podobieństwa semantycznego, a potem policzy go z ``semantic_similarity=None``
    (0 z 60 punktów) i zapisze jako świeży pod NOWĄ wersją — czyli utrwali
    zaniżony wynik, którego już nic nie przeliczy.
    """
    conds = [
        CandidateJobMatchScore.job_id == job_id,
        CandidateJobMatchScore.profile_id == profile_id,
        CandidateJobMatchScore.stale.is_(False),
        CandidateJobMatchScore.scoring_algorithm_version == scoring_algorithm_version(),
    ]
    if candidate_ids is not None:
        conds.append(CandidateJobMatchScore.candidate_id.in_(candidate_ids))
    return conds


def _breakdown_from_row(row: CandidateJobMatchScore) -> ScoreBreakdown:
    """Hydrate a ScoreBreakdown dataclass from a persisted row."""
    b = row.breakdown or {}

    def layer(key: str) -> LayerResult:
        d = b.get(key, {}) or {}
        return LayerResult(
            points=float(d.get("points", 0.0)),
            max_points=float(d.get("max", 0.0)),
            reason=str(d.get("reason", "") or ""),
            status=str(d["status"]) if d.get("status") is not None else None,
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


def _ledger_invalidated_mid_compute(
    *, candidate_id: int, job_id: int, profile_id: int, compute_start: datetime
):
    """SQL predicate: did a persisted invalidation land after ``compute_start``?

    Reads the ledger's newest ``last_invalidated_at`` across the three keys that
    make up the cache key — (candidate), (job), (profile) — as a scalar subquery.
    ``NULL`` (no invalidation on record) compares to ``False``. Evaluated inside
    the INSERT statement so the read is atomic with the row write on the miss path
    (no separate SELECT-then-INSERT gap): the dominant race — an edit's
    ``mark_stale_*`` committing the ledger BEFORE a late miss-compute writes back —
    is caught here and the row is persisted stale instead of falsely fresh.
    """
    newest_invalidation = (
        select(func.max(MatchScoreInvalidation.last_invalidated_at)).where(
            or_(
                and_(
                    MatchScoreInvalidation.entity_type == "candidate",
                    MatchScoreInvalidation.entity_id == candidate_id,
                ),
                and_(
                    MatchScoreInvalidation.entity_type == "job",
                    MatchScoreInvalidation.entity_id == job_id,
                ),
                and_(
                    MatchScoreInvalidation.entity_type == "profile",
                    MatchScoreInvalidation.entity_id == profile_id,
                ),
            )
        )
    ).scalar_subquery()
    return newest_invalidation >= compute_start


async def _touch_invalidation_ledger(
    db: AsyncSession, entity_type: str, entity_ids: Iterable[int]
) -> None:
    """UPSERT ledger rows to ``now()`` for ``entity_ids`` — the miss-path trace.

    Called by every ``mark_stale_*`` so an invalidation is durably recorded EVEN
    WHEN no cache row exists yet (the exact hole the on-row ``invalidated_at``
    fence cannot cover). Runs in the caller's transaction, committing atomically
    with the accompanying cache ``UPDATE``.
    """
    ids = [i for i in dict.fromkeys(entity_ids) if i is not None]
    if not ids:
        return
    stmt = pg_insert(MatchScoreInvalidation).values(
        [{"entity_type": entity_type, "entity_id": i} for i in ids]
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[
            MatchScoreInvalidation.entity_type,
            MatchScoreInvalidation.entity_id,
        ],
        set_={"last_invalidated_at": func.now()},
    )
    await db.execute(stmt)


async def _upsert_breakdown(
    db: AsyncSession,
    breakdown: ScoreBreakdown,
    *,
    profile_id: int,
    compute_start: datetime,
) -> None:
    """Persist (insert-or-update) a computed breakdown; conditionally sets `stale`.

    CAS fence (P1-MATCH-02 + F-28): a compute that STARTED before a concurrent
    ``mark_stale_*`` must never persist a falsely fresh cache row. ``compute_start``
    is the DB clock captured *before* scoring began.

    - Conflict (row exists): ``mark_stale_*`` stamped ``invalidated_at`` on the row;
      we clear ``stale`` only when the row was NOT invalidated after this compute
      began (``invalidated_at IS NULL OR invalidated_at < compute_start``).
    - Insert (miss, no row): there is no row to carry ``invalidated_at``, so we
      consult the persistent invalidation LEDGER instead (F-28). If an invalidation
      for this candidate/job/profile landed at or after ``compute_start``, the row
      is inserted ``stale=True``; otherwise ``stale=False``.

    The freshly computed breakdown is written either way — only the staleness
    verdict is gated.
    """
    stale_on_insert = case(
        (
            _ledger_invalidated_mid_compute(
                candidate_id=breakdown.candidate_id,
                job_id=breakdown.job_id,
                profile_id=profile_id,
                compute_start=compute_start,
            ),
            True,
        ),
        else_=False,
    )
    stmt = pg_insert(CandidateJobMatchScore).values(
        candidate_id=breakdown.candidate_id,
        job_id=breakdown.job_id,
        profile_id=profile_id,
        total_score=breakdown.total,
        breakdown=breakdown.as_dict(),
        stale=stale_on_insert,
        scoring_algorithm_version=scoring_algorithm_version(),
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
            "scoring_algorithm_version": scoring_algorithm_version(),
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
    # Świeżość rozstrzyga ZAPYTANIE, nie kod po nim. Wersja z ręcznym warunkiem
    # w Pythonie (``not row.stale and row.scoring_algorithm_version == …``) była
    # czwartą kopią tej samej reguły — poprawną, ale kopią, a #32 powstało
    # dokładnie z rozjechania się kopii. Strażnik jej nie widział, bo szukał
    # atrybutu KLASY w zapytaniu, a ta sięgała po atrybut INSTANCJI.
    row = await db.scalar(
        select(CandidateJobMatchScore).where(
            *fresh_score_conditions(
                job_id=job.id,
                profile_id=profile.id,
                candidate_ids=[candidate.id],
            )
        )
    )
    if row is not None:
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
    semantic_unavailable_ids: Optional[set[int]] = None,
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
    unavailable_ids = semantic_unavailable_ids or set()
    cached_rows = (
        (
            await db.execute(
                select(CandidateJobMatchScore).where(
                    *fresh_score_conditions(
                        job_id=job.id,
                        profile_id=profile.id,
                        candidate_ids=[c.id for c in candidates],
                    )
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
    # The cache read above is batched, but the cold path below was not: each miss
    # issued two more SELECTs inside `score_candidate_job`, so a fully cold pool
    # of N cost 2N round-trips regardless of this function's bulk read. Build the
    # per-job context once for the misses only — a fully warm call still does no
    # extra work.
    misses = [c.id for c in candidates if c.id not in cached_by_cid]
    context = await build_job_scoring_context(db, job, misses) if misses else None
    for c in candidates:
        row = cached_by_cid.get(c.id)
        if row is not None:
            results.append(_breakdown_from_row(row))
            continue
        breakdown = await score_candidate_job(
            c,
            job,
            db,
            semantic_similarity=sims.get(c.id),
            profile=profile,
            context=context,
            # „Nie zmierzyliśmy" vs „zmierzono i nie ma wektora" (#414). Bez
            # tego rozróżnienia awaria dostawcy zapisuje się w breakdownie jako
            # zarzut wobec profilu kandydata.
            semantic_unavailable=c.id in unavailable_ids,
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
    """Mark all (candidate, *) cached rows stale. Returns row count affected.

    Also stamps the persistent invalidation ledger (F-28) so a concurrent
    miss-compute that finds no cache row still learns this candidate was
    invalidated and cannot persist a falsely fresh row.
    """
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.candidate_id == candidate_id)
        .values(stale=True, invalidated_at=func.now())
    )
    await _touch_invalidation_ledger(db, "candidate", [candidate_id])
    return res.rowcount or 0


async def mark_stale_for_job(db: AsyncSession, job_id: int) -> int:
    """Mark all (*, job) cached rows stale. Returns row count affected.

    Also stamps the persistent invalidation ledger (F-28) — see
    :func:`mark_stale_for_candidate`.
    """
    res = await db.execute(
        update(CandidateJobMatchScore)
        .where(CandidateJobMatchScore.job_id == job_id)
        .values(stale=True, invalidated_at=func.now())
    )
    await _touch_invalidation_ledger(db, "job", [job_id])
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
    await _touch_invalidation_ledger(db, "profile", [profile_id])
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
    await _touch_invalidation_ledger(db, "candidate", ids)
    return res.rowcount or 0
