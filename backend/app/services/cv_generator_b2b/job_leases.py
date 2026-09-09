"""Atomic database transitions; no provider call can run before a claim commits."""

from contextvars import ContextVar
from contextlib import contextmanager

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


async def interrupt_expired_jobs(db) -> list[int]:
    """Fence expired owners without replaying an uncertain provider request.

    The caller owns the transaction so related UI rows can change atomically.
    Queued and freshly renewed attempts are deliberately unaffected.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(CvGenerationJob)
        .where(
            CvGenerationJob.status == "running",
            CvGenerationJob.lease_expires_at <= now,
        )
        .values(
            status="interrupted",
            finished_at=now,
            lease_token=None,
            lease_expires_at=None,
            error_code="worker_lease_expired",
        )
        .returning(CvGenerationJob.id)
    )
    return list(result.scalars().all())


# The context propagates to the worker task and threadpool, but contains no PII.

_active_owner: ContextVar[tuple[int, str] | None] = ContextVar(
    "cv_job_owner", default=None
)


@contextmanager
def owned_job(job_id: int, token: str):
    reset = _active_owner.set((job_id, token))
    try:
        yield
    finally:
        _active_owner.reset(reset)


async def lock_owned_job(db):
    """Fence result writes in the same transaction as their subsequent commit."""
    from sqlalchemy import select

    owner = _active_owner.get()
    if owner is None:
        return (
            None  # Legacy direct callers; durable execution always installs ownership.
        )
    job_id, token = owner
    job = await db.scalar(
        select(CvGenerationJob)
        .where(
            CvGenerationJob.id == job_id,
            CvGenerationJob.status == "running",
            CvGenerationJob.lease_token == token,
            CvGenerationJob.lease_expires_at > datetime.now(timezone.utc),
        )
        .with_for_update()
    )
    if job is None:
        raise RuntimeError("CV job lease lost before write")
    return job


async def register_second_document(db, generated_id: int):
    job = await lock_owned_job(db)
    if job is not None:
        if (
            job.second_generated_id is not None
            and job.second_generated_id != generated_id
        ):
            raise RuntimeError("CV job already has a second language document")
        job.second_generated_id = generated_id
