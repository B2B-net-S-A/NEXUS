"""F-28 — a miss-path write-back cannot persist a falsely fresh cache row.

Sibling to ``test_match_cache_cas.py`` (P1-MATCH-02), which proves the *conflict*
(row-exists) write-back honours ``invalidated_at``. That fence lives ON the cache
row, so it protects nothing on the *miss* path: when no cache row exists yet, a
``mark_stale_*`` updates zero rows and leaves no trace, and an in-flight
miss-compute then INSERTs ``stale=False`` against the OLD inputs — falsely fresh
forever.

The fix is a persistent invalidation ledger (``match_score_invalidations``):
``mark_stale_*`` UPSERTs ``last_invalidated_at`` even with no cache row, and the
miss/INSERT path reads it to gate the ``stale`` verdict.

Behavioural test against a real Postgres — the ledger CAS lives in SQL, so mocks
would not prove it. Run locally with ``import app.main`` first so the ORM registry
is configured.
"""

from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace

from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.match_score import CandidateJobMatchScore
from app.models.match_score_invalidation import MatchScoreInvalidation
from app.services.match_score_cache import (
    _upsert_breakdown,
    mark_stale_for_candidate,
)

_PROFILE_ID = 0  # built-in DEFAULT_PROFILE


async def _make_candidate_and_job(db, tag: str) -> tuple[int, int]:
    client = Client(name=f"F28 Client {tag}")
    cand = Candidate(name="F28", lastname=f"Miss-{tag}")
    db.add_all([client, cand])
    await db.flush()
    job = Job(title=f"F28 Job {tag}", client_id=client.id)
    db.add(job)
    await db.flush()
    return cand.id, job.id


async def _row(db, cand_id: int, job_id: int) -> CandidateJobMatchScore | None:
    return await db.scalar(
        select(CandidateJobMatchScore).where(
            CandidateJobMatchScore.candidate_id == cand_id,
            CandidateJobMatchScore.job_id == job_id,
            CandidateJobMatchScore.profile_id == _PROFILE_ID,
        )
    )


def _breakdown(cand_id: int, job_id: int):
    return SimpleNamespace(
        candidate_id=cand_id, job_id=job_id, total=55.0, as_dict=lambda: {"v": 1}
    )


async def test_miss_writeback_after_invalidation_persists_stale() -> None:
    """mark_stale during an in-flight MISS-compute → the late INSERT is stale.

    There is NO pre-existing cache row (the whole point of F-28), so the on-row
    ``invalidated_at`` fence has nothing to bite on. The ledger must carry the
    invalidation across to the INSERT.
    """
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand_id, job_id = await _make_candidate_and_job(db, u)
        await db.commit()

        assert await _row(db, cand_id, job_id) is None, "precondition: cache miss"

        # (1) A miss-compute begins: capture the DB clock BEFORE it would finish.
        compute_start = await db.scalar(select(func.now()))
        await db.commit()  # close txn so mark_stale gets a strictly later now()
        await asyncio.sleep(0.02)

        # (2) An invalidation lands WHILE that compute is still running. No cache
        #     row exists, so the cache UPDATE touches nothing — only the ledger
        #     records it.
        await mark_stale_for_candidate(db, cand_id)
        await db.commit()

        ledger = await db.scalar(
            select(MatchScoreInvalidation).where(
                MatchScoreInvalidation.entity_type == "candidate",
                MatchScoreInvalidation.entity_id == cand_id,
            )
        )
        assert ledger is not None, "mark_stale must record the ledger even on a miss"

        # (3) The stale-started compute writes back with its pre-invalidation start.
        await _upsert_breakdown(
            db,
            _breakdown(cand_id, job_id),
            profile_id=_PROFILE_ID,
            compute_start=compute_start,
        )
        await db.commit()

        row = await _row(db, cand_id, job_id)
        assert row is not None, "write-back must persist a row"
        assert row.stale is True, (
            "miss-path write-back inserted stale=False after an invalidation; "
            "the ledger CAS was lost (F-28)"
        )


async def test_miss_writeback_without_invalidation_is_fresh() -> None:
    """No invalidation on record → the miss-path INSERT is fresh (stale=False).

    Guards against the fence sticking permanently / a false-stale regression.
    """
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cand_id, job_id = await _make_candidate_and_job(db, u)
        await db.commit()

        assert await _row(db, cand_id, job_id) is None, "precondition: cache miss"

        # Compute starts and writes back with NO intervening mark_stale.
        compute_start = await db.scalar(select(func.now()))
        await db.commit()
        await _upsert_breakdown(
            db,
            _breakdown(cand_id, job_id),
            profile_id=_PROFILE_ID,
            compute_start=compute_start,
        )
        await db.commit()

        row = await _row(db, cand_id, job_id)
        assert row is not None
        assert row.stale is False, "an uncontended miss compute must be fresh"
