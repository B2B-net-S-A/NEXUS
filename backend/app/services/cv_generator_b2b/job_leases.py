"""Atomic database transitions; no provider call can run before a claim commits."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import update

from app.models.cv_generation_job import CvGenerationJob

LEASE_SECONDS = 180


async def claim_job(db, job_id: int) -> str | None:
    token = str(uuid4())
    result = await db.execute(
        update(CvGenerationJob)
        .where(CvGenerationJob.id == job_id, CvGenerationJob.status == "queued")
        .values(
            status="running",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=LEASE_SECONDS),
        )
        .returning(CvGenerationJob.id)
    )
    claimed = result.scalar_one_or_none()
    await db.commit()
    return token if claimed is not None else None


async def heartbeat_job(db, job_id: int, token: str) -> bool:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(CvGenerationJob)
        .where(
            CvGenerationJob.id == job_id,
            CvGenerationJob.status == "running",
            CvGenerationJob.lease_token == token,
            CvGenerationJob.lease_expires_at > now,
        )
        .values(lease_expires_at=now + timedelta(seconds=LEASE_SECONDS))
        .returning(CvGenerationJob.id)
    )
    renewed = result.scalar_one_or_none() is not None
    await db.commit()
    return renewed


async def finish_job(db, job_id: int, token: str, *, failed: bool = False) -> bool:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(CvGenerationJob)
        .where(
            CvGenerationJob.id == job_id,
            CvGenerationJob.status == "running",
            CvGenerationJob.lease_token == token,
            CvGenerationJob.lease_expires_at > now,
        )
        .values(
            status="failed" if failed else "complete",
            finished_at=now,
            lease_token=None,
            lease_expires_at=None,
        )
        .returning(CvGenerationJob.id)
    )
    finished = result.scalar_one_or_none() is not None
    await db.commit()
    return finished
