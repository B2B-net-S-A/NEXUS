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
