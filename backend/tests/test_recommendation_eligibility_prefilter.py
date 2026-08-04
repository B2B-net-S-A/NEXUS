"""P0-A: hard eligibility prefilter on the recommendations / snapshot pool.

`filter_eligible_candidates` (services/pipeline_eligibility.py) drops candidates
the recruiter could NOT assign — global blacklist, active client
blacklist/NDA/competitor conflict, hiring-manager veto — from the ranking pool
BEFORE scoring, while keeping soft warnings (current employment, candidate
excluded) and expired conflicts. It mirrors the assign gate so
"recommended ⟹ assignable". These are unit tests on the shared helper directly,
independent of Qdrant / the scoring stack.

Uses the in-process real-postgres fixtures' DB (AsyncSessionLocal) from conftest.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select


async def _seed_candidate(status: str = "active") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Prefilter",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"pref-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus(status),
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PrefClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Pref-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, cli.id


async def _seed_conflict(
    candidate_id: int,
    client_id: int,
    type_: str,
    expires_at: datetime | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_conflict import CandidateConflict, ConflictType

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConflict(
                candidate_id=candidate_id,
                client_id=client_id,
                type=ConflictType(type_),
                active=True,
                expires_at=expires_at,
            )
        )
        await db.commit()


async def _run_filter(job_id: int, candidate_ids: list[int]) -> set[int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.services.pipeline_eligibility import filter_eligible_candidates

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == job_id))
        cands = list(
            (await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))))
            .scalars()
            .all()
        )
        kept = await filter_eligible_candidates(
            db, job=job, candidates=cands, now=datetime.now(timezone.utc)
        )
        return {c.id for c in kept}


async def test_prefilter_drops_blacklisted_keeps_clean():
    job_id, _client_id = await _seed_job()
    clean = await _seed_candidate()
    black = await _seed_candidate(status="blacklisted")

    kept = await _run_filter(job_id, [clean, black])

    assert clean in kept
    assert black not in kept


async def test_prefilter_drops_active_hard_conflict():
    job_id, client_id = await _seed_job()
    clean = await _seed_candidate()
    nda = await _seed_candidate()
    await _seed_conflict(nda, client_id, "nda")

    kept = await _run_filter(job_id, [clean, nda])

    assert kept == {clean}


async def test_prefilter_keeps_expired_conflict():
    """An expired hard conflict is not active — the candidate stays eligible."""
    job_id, client_id = await _seed_job()
    expired = await _seed_candidate()
    await _seed_conflict(
        expired,
        client_id,
        "blacklist",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )

    kept = await _run_filter(job_id, [expired])

    assert expired in kept


async def test_prefilter_keeps_soft_current_employment():
    """Current employment at the client is a warning, not a hard block."""
    job_id, client_id = await _seed_job()
    soft = await _seed_candidate()
    await _seed_conflict(soft, client_id, "current_employment")

    kept = await _run_filter(job_id, [soft])

    assert soft in kept
