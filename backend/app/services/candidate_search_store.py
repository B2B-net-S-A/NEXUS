"""Transactional storage for exhaustive searches and restart-safe batch leases.

All functions use the caller's transaction. A worker must commit each batch;
no process-local status is considered evidence of completion.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, insert, or_, select, update

from app.models.candidate_search_run import CandidateSearchResult, CandidateSearchRun
from app.services.full_candidate_scan import (
    CandidateEvaluation,
    CandidateSnapshot,
    snapshot_candidate_population,
)


class SearchLeaseLost(RuntimeError):
    pass


async def create_run(
    db,
    *,
    actor_id: int,
    client_id: int,
    job_id: int | None,
    request_fingerprint: str,
    request_context: dict,
    version_trace: dict,
):
    run = CandidateSearchRun(
        id=str(uuid.uuid4()),
        created_by=actor_id,
        client_id=client_id,
        job_id=job_id,
        state="queued",
        request_fingerprint=request_fingerprint,
        request_context=request_context,
        version_trace=version_trace,
        population_size=0,
        metrics={},
    )
    db.add(run)
    await db.flush()
    # One statement fixes membership before any scoring or top-K retrieval.
    population = await snapshot_candidate_population(db)
    for start in range(0, len(population), 500):
        await db.execute(
            insert(CandidateSearchResult),
            [
                {
                    "run_id": run.id,
                    "candidate_id": item.candidate_id,
                    "candidate_version": item.version,
                    "state": "pending",
                }
                for item in population[start : start + 500]
            ],
        )
    run.population_size = len(population)
    await db.flush()
    return run


async def claim_run(db, run_id: str, *, lease_seconds: int = 120) -> str | None:
    now = datetime.now(timezone.utc)
    token = str(uuid.uuid4())
    claimed = await db.execute(
        update(CandidateSearchRun)
        .where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.state.in_(["queued", "running"]),
            or_(
                CandidateSearchRun.lease_expires_at.is_(None),
                CandidateSearchRun.lease_expires_at < now,
            ),
        )
        .values(
            state="running",
            lease_token=token,
            lease_expires_at=now + timedelta(seconds=lease_seconds),
        )
        .returning(CandidateSearchRun.id)
    )
    return token if claimed.scalar_one_or_none() else None


async def _locked_run(db, run_id: str, token: str):
    run = await db.scalar(
        select(CandidateSearchRun)
        .where(CandidateSearchRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        run is None
        or run.state != "running"
        or run.lease_token != token
        or run.lease_expires_at is None
        or run.lease_expires_at <= datetime.now(timezone.utc)
    ):
        raise SearchLeaseLost("Search run lease expired or was replaced")
    return run


async def pending_batch(
    db, run_id: str, *, limit: int = 256
) -> list[CandidateSnapshot]:
    if not 1 <= limit <= 1000:
        raise ValueError("Invalid batch size")
    rows = await db.execute(
        select(
            CandidateSearchResult.candidate_id, CandidateSearchResult.candidate_version
        )
        .where(
            CandidateSearchResult.run_id == run_id,
            CandidateSearchResult.state == "pending",
        )
        .order_by(CandidateSearchResult.candidate_id)
        .limit(limit)
    )
    return [CandidateSnapshot(cid, version) for cid, version in rows]


async def save_batch(
    db,
    run_id: str,
    token: str,
    batch: list[CandidateSnapshot],
    evaluations: list[CandidateEvaluation],
    *,
    error_code: str | None = None,
):
    run = await _locked_run(db, run_id, token)
    expected = {item.candidate_id: item.version for item in batch}
    by_id = {item.candidate_id: item for item in evaluations}
    if (
        len(by_id) != len(evaluations)
        or by_id.keys() - expected.keys()
        or len(expected) != len(batch)
    ):
        raise ValueError("Duplicate or foreign evaluation ID")
    for cid, version in expected.items():
        value = by_id.get(cid)
        valid = value is not None and value.candidate_version == version
        fields = {
            "state": "evaluated" if valid else "failed",
            "eligible": value.eligible if valid else None,
            "fit_score": value.fit_score if valid else None,
            "measurement": value.measurement if valid else "stale",
            "evidence": value.evidence if valid else None,
            "exclusion_reasons": list(value.exclusion_reasons) if valid else [],
        }
        await db.execute(
            update(CandidateSearchResult)
            .where(
                CandidateSearchResult.run_id == run_id,
                CandidateSearchResult.candidate_id == cid,
                CandidateSearchResult.candidate_version == version,
                CandidateSearchResult.state == "pending",
            )
            .values(**fields)
        )
    run.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=120)
    if error_code:
        run.error_code = error_code[:100]
    await db.flush()


async def run_counts(db, run_id: str) -> dict:
    row = (
        (
            await db.execute(
                select(
                    func.count().label("population"),
                    func.count()
                    .filter(CandidateSearchResult.state == "pending")
                    .label("pending"),
                    func.count()
                    .filter(CandidateSearchResult.state == "failed")
                    .label("failed"),
                    func.count()
                    .filter(CandidateSearchResult.state == "evaluated")
                    .label("evaluated"),
                    func.count()
                    .filter(CandidateSearchResult.eligible.is_(True))
                    .label("eligible"),
                    func.count()
                    .filter(
                        CandidateSearchResult.eligible.is_(True),
                        CandidateSearchResult.fit_score >= 75,
                    )
                    .label("strong"),
                    func.count()
                    .filter(CandidateSearchResult.eligible.is_(False))
                    .label("excluded"),
                    func.count()
                    .filter(
                        CandidateSearchResult.eligible.is_(True),
                        CandidateSearchResult.measurement != "measured",
                    )
                    .label("needs_verification"),
                ).where(CandidateSearchResult.run_id == run_id)
            )
        )
        .mappings()
        .one()
    )
    return dict(row)


async def finish_run(db, run_id: str, token: str):
    run = await _locked_run(db, run_id, token)
    counts = await run_counts(db, run_id)
    if counts["pending"] or counts["population"] != run.population_size:
        raise ValueError("Cannot finalize a run with unaccounted population")
    run.state = (
        "partial" if counts["failed"] or counts["needs_verification"] else "complete"
    )
    run.completed_at = datetime.now(timezone.utc)
    run.lease_token = None
    run.lease_expires_at = None
    await db.flush()
    return counts


async def owned_run(db, run_id: str, actor_id: int):
    """No cross-user reuse/access; resource authorization is also rechecked by API."""
    return await db.scalar(
        select(CandidateSearchRun).where(
            CandidateSearchRun.id == run_id,
            CandidateSearchRun.created_by == actor_id,
        )
    )


async def result_page(
    db,
    run_id: str,
    *,
    offset: int = 0,
    limit: int = 20,
    min_score: float = 0,
    filters=None,
):
    if offset < 0 or not 1 <= limit <= 100 or not 0 <= min_score <= 100:
        raise ValueError("Invalid page")
    conditions = (
        CandidateSearchResult.run_id == run_id,
        CandidateSearchResult.state == "evaluated",
        CandidateSearchResult.eligible.is_(True),
        or_(
            CandidateSearchResult.fit_score.is_(None),
            CandidateSearchResult.fit_score >= min_score,
        ),
    )
    if filters is not None:
        conditions = (*conditions, *filters.conditions())
    total = await db.scalar(
        select(func.count()).select_from(CandidateSearchResult).where(*conditions)
    )
    rows = (
        (
            await db.execute(
                select(CandidateSearchResult)
                .where(*conditions)
                .order_by(
                    CandidateSearchResult.fit_score.desc().nulls_last(),
                    CandidateSearchResult.candidate_id,
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return rows, total


async def population_changed(db, run_id: str) -> bool:
    """Invalidate a frozen ranking after any member changes or membership shifts."""
    from sqlalchemy import DateTime, and_, cast, exists
    from app.models.candidate import Candidate

    changed = exists(
        select(CandidateSearchResult.candidate_id)
        .outerjoin(
            Candidate,
            Candidate.id == CandidateSearchResult.candidate_id,
        )
        .where(
            CandidateSearchResult.run_id == run_id,
            or_(
                Candidate.id.is_(None),
                Candidate.updated_at
                != cast(
                    CandidateSearchResult.candidate_version, DateTime(timezone=True)
                ),
            ),
        )
    )
    added = exists(
        select(Candidate.id)
        .outerjoin(
            CandidateSearchResult,
            and_(
                CandidateSearchResult.candidate_id == Candidate.id,
                CandidateSearchResult.run_id == run_id,
            ),
        )
        .where(CandidateSearchResult.candidate_id.is_(None))
    )
    return bool(await db.scalar(select(or_(changed, added))))
