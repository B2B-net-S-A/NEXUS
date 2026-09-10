"""Committed ownership of one paid review attempt; expired work is never replayed."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import func, select, update
from app.models.cv_approval_job import CvApprovalJob

LEASE_SECONDS = 180
MAX_RUNNING_REVIEWS = 2
CLAIM_LOCK_KEY = 0x4356415050


def owned(job_id, token):
    return (
        CvApprovalJob.id == job_id,
        CvApprovalJob.status == "running",
        CvApprovalJob.lease_token == token,
        CvApprovalJob.lease_expires_at > datetime.now(timezone.utc),
    )


async def claim_review(db, job_id: int) -> str | None:
    await db.execute(select(func.pg_advisory_xact_lock(CLAIM_LOCK_KEY)))
    running = await db.scalar(
        select(func.count())
        .select_from(CvApprovalJob)
        .where(CvApprovalJob.status == "running")
    )
    if running >= MAX_RUNNING_REVIEWS:
        await db.commit()
        return None
    token = str(uuid4())
    claimed = await db.scalar(
        update(CvApprovalJob)
        .where(
            CvApprovalJob.id == job_id,
            CvApprovalJob.status == "queued",
            CvApprovalJob.input_content.is_not(None),
        )
        .values(
            status="running",
            lease_token=token,
            lease_expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=LEASE_SECONDS),
        )
        .returning(CvApprovalJob.id)
    )
    await db.commit()
    return token if claimed is not None else None


async def heartbeat_review(db, job_id: int, token: str) -> bool:
    renewed = await db.scalar(
        update(CvApprovalJob)
        .where(*owned(job_id, token))
        .values(
            lease_expires_at=datetime.now(timezone.utc)
            + timedelta(seconds=LEASE_SECONDS)
        )
        .returning(CvApprovalJob.id)
    )
    await db.commit()
    return renewed is not None


async def finish_review(
    db, job_id: int, token: str, *, status: str, result=None, error_code=None
) -> bool:
    """Store verification evidence, never approve a document or update its draft."""
    if status not in {"verified", "rejected", "failed"}:
        raise ValueError("Invalid terminal review status")
    if status == "verified" and (
        not isinstance(result, dict) or result.get("status") != "verified"
    ):
        raise ValueError("Verified review requires evidence")
    finished = await db.scalar(
        update(CvApprovalJob)
        .where(*owned(job_id, token))
        .values(
            status=status,
            result=result if status == "verified" else None,
            error_code=error_code,
            input_content=None,
            lease_token=None,
            lease_expires_at=None,
            finished_at=datetime.now(timezone.utc),
        )
        .returning(CvApprovalJob.id)
    )
    await db.commit()
    return finished is not None


async def interrupt_expired_reviews(db) -> list[int]:
    """Caller commits; neither a queued job nor an uncertain bill is retried."""
    rows = await db.scalars(
        update(CvApprovalJob)
        .where(
            CvApprovalJob.status == "running",
            CvApprovalJob.lease_expires_at <= datetime.now(timezone.utc),
        )
        .values(
            status="interrupted",
            input_content=None,
            result=None,
            error_code="worker_lease_expired",
            lease_token=None,
            lease_expires_at=None,
            finished_at=datetime.now(timezone.utc),
        )
        .returning(CvApprovalJob.id)
    )
    return list(rows.all())


async def cancel_review(db, job_id: int) -> bool:
    """Caller authorizes and commits. In-flight provider cost cannot be undone."""
    cancelled = await db.scalar(
        update(CvApprovalJob)
        .where(
            CvApprovalJob.id == job_id,
            CvApprovalJob.status.in_(("queued", "running")),
        )
        .values(
            status="cancelled",
            input_content=None,
            result=None,
            lease_token=None,
            lease_expires_at=None,
            finished_at=datetime.now(timezone.utc),
        )
        .returning(CvApprovalJob.id)
    )
    return cancelled is not None
