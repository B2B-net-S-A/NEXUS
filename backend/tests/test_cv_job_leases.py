"""PostgreSQL ownership races; runs against the hosted CI database."""

import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from app.core.database import AsyncSessionLocal
from app.models.cv_generation_job import CvGenerationJob
from app.services.cv_generator_b2b.job_leases import (
    claim_job,
    finish_job,
    heartbeat_job,
)


async def test_only_one_worker_claims_and_expired_owner_cannot_finish():
    async with AsyncSessionLocal() as db:
        job = CvGenerationJob(
            kind="upload",
            status="queued",
            input_storage_key="test-only/no-object",
            input_sha256="a" * 64,
        )
        db.add(job)
        await db.flush()
        job_id = job.id
        await db.commit()

    async def claim():
        async with AsyncSessionLocal() as db:
            return await claim_job(db, job_id)

    try:
        claims = await asyncio.gather(claim(), claim())
        tokens = [token for token in claims if token is not None]
        assert len(tokens) == 1
        token = tokens[0]
        async with AsyncSessionLocal() as db:
            assert not await heartbeat_job(db, job_id, "wrong-owner")
            assert not await finish_job(db, job_id, "wrong-owner")
            assert await heartbeat_job(db, job_id, token)
            await db.execute(
                update(CvGenerationJob)
                .where(CvGenerationJob.id == job_id)
                .values(
                    lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )
            )
            await db.commit()
            assert not await heartbeat_job(db, job_id, token)
            assert not await finish_job(db, job_id, token)
            # A billed attempt cannot become a new queued attempt implicitly.
            assert await claim_job(db, job_id) is None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvGenerationJob).where(CvGenerationJob.id == job_id)
            )
            await db.commit()


async def test_reaper_preserves_queued_and_live_work_and_fences_expired_owner():
    from app.services.cv_generator_b2b.job_leases import interrupt_expired_jobs

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        jobs = [
            CvGenerationJob(
                kind="upload",
                status=status,
                input_storage_key="test-only/no-object",
                input_sha256="b" * 64,
                lease_token="test-owner" if status == "running" else None,
                lease_expires_at=expires,
            )
            for status, expires in [
                ("queued", None),
                ("running", now + timedelta(minutes=10)),
                ("running", now - timedelta(minutes=1)),
            ]
        ]
        db.add_all(jobs)
        await db.flush()
        ids = [job.id for job in jobs]
        await db.commit()
    try:
        async with AsyncSessionLocal() as db:
            interrupted = await interrupt_expired_jobs(db)
            await db.commit()
            assert ids[2] in interrupted
            assert ids[0] not in interrupted
            assert ids[1] not in interrupted
            assert not await finish_job(db, ids[2], "test-owner")
            assert await claim_job(db, ids[2]) is None
            assert await heartbeat_job(db, ids[1], "test-owner")
            assert await claim_job(db, ids[0]) is not None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(CvGenerationJob).where(CvGenerationJob.id.in_(ids)))
            await db.commit()
