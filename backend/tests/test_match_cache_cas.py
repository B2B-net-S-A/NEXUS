"""P1-MATCH-02 — the match-score cache write-back cannot resurrect a stale row.

``_upsert_breakdown`` used to clear ``stale=False`` unconditionally on conflict.
A score compute that STARTED before a ``mark_stale_*`` therefore overwrote the
invalidation when it finally wrote back — serving a stale score.

The fix adds ``invalidated_at`` (DB clock, stamped by ``mark_stale_*``) and a
compare-and-swap fence: the write-back clears ``stale`` only when the row was not
invalidated after the compute began
(``invalidated_at IS NULL OR invalidated_at < compute_start``).

Behavioural test against a real Postgres — the fence lives in SQL, so mocks would
not prove it. Run locally with ``import app.main`` first so the ORM registry is
configured.
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
from app.services.match_score_cache import _upsert_breakdown, mark_stale_for_candidate

_PROFILE_ID = 0  # built-in DEFAULT_PROFILE


async def _fresh_score_row(db, cand_id: int, job_id: int) -> None:
    db.add(
        CandidateJobMatchScore(
            candidate_id=cand_id,
            job_id=job_id,
            profile_id=_PROFILE_ID,
            total_score=50.0,
            breakdown={},
            scoring_algorithm_version="test",
            stale=False,
        )
    )
    await db.commit()


async def _stale_of(db, cand_id: int, job_id: int) -> bool:
    return await db.scalar(
        select(CandidateJobMatchScore.stale).where(
            CandidateJobMatchScore.candidate_id == cand_id,
            CandidateJobMatchScore.job_id == job_id,
            CandidateJobMatchScore.profile_id == _PROFILE_ID,
        )
    )


async def test_late_writeback_after_invalidation_keeps_row_stale() -> None:
    """mark_stale during an in-flight compute → the late upsert stays stale."""
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"CAS Client {u}")
        cand = Candidate(name="CAS", lastname=f"Race-{u}")
        db.add_all([client, cand])
        await db.flush()
        job = Job(title=f"CAS Job {u}", client_id=client.id)
        db.add(job)
        await db.flush()
        await _fresh_score_row(db, cand.id, job.id)

        breakdown = SimpleNamespace(
            candidate_id=cand.id, job_id=job.id, total=55.0, as_dict=lambda: {"v": 1}
        )

        # (1) A compute begins: capture the DB clock BEFORE it would finish.
        compute_start = await db.scalar(select(func.now()))
        await db.commit()  # close the txn so mark_stale gets a strictly later now()
        await asyncio.sleep(0.02)

        # (2) An invalidation lands WHILE that compute is still running.
        await mark_stale_for_candidate(db, cand.id)
        await db.commit()

        # (3) The stale-started compute writes back with its pre-invalidation start.
        await _upsert_breakdown(
            db, breakdown, profile_id=_PROFILE_ID, compute_start=compute_start
        )
        await db.commit()

        assert await _stale_of(db, cand.id, job.id) is True, (
            "late write-back resurrected stale=False; invalidation was lost"
        )

        # (4) Positive control: a compute that STARTS AFTER the invalidation
        # publishes a fresh row (fence must not stick permanently).
        compute_start2 = await db.scalar(select(func.now()))
        await db.commit()
        await _upsert_breakdown(
            db, breakdown, profile_id=_PROFILE_ID, compute_start=compute_start2
        )
        await db.commit()

        assert await _stale_of(db, cand.id, job.id) is False, (
            "a compute started after the invalidation should clear stale"
        )
