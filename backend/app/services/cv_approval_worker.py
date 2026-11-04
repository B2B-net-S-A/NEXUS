"""Durable review execution. Produces evidence; never approves mutable drafts."""

import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import select
from app.core.database import AsyncSessionLocal
from app.models.cv_approval_job import CvApprovalJob
from app.models.cv_generated_draft import CvGeneratedDraft
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.user import User
from app.services.cv_approval_snapshot import deserialize_review
from app.services.cv_approval_review import execute_approval_review
from app.services import cv_approval_leases as leases
from app.services.lease_renewal import renew_lease

logger = logging.getLogger(__name__)


async def renew(job_id, token):
    # Runda 7 (R7-N6-2): przejściowy błąd bazy nie kończy opłaconej kontroli.
    async def beat() -> bool:
        async with AsyncSessionLocal() as db:
            return await leases.heartbeat_review(db, job_id, token)

    await renew_lease(beat, lease_seconds=leases.LEASE_SECONDS, label="CV review")


async def execute_review_job(job_id: int):
    async with AsyncSessionLocal() as db:
        token = await leases.claim_review(db, job_id)
    if not token:
        return
    verification = heartbeat = None
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(CvApprovalJob, job_id)
            if job is None or job.status != "running" or job.lease_token != token:
                return
            if job.input_content is None:
                raise ValueError("Missing input")
            prepared = deserialize_review(job.input_content, job.input_sha256)
            draft = (
                await db.get(CvGeneratedDraft, job.generated_draft_id)
                if job.generated_draft_id
                else await db.get(CandidateStageCV, job.candidate_stage_cv_id)
            )
            if (
                draft is None
                or draft.edit_revision != job.expected_revision
                or draft.branded_status != "draft"
                or draft.generated_document_id != prepared.generated_id
                or job.generated_document_id != prepared.generated_id
            ):
                raise ValueError("Review target changed")
            user_id = job.user_id
            user = await db.get(User, user_id) if user_id is not None else None
            if user is None or not user.is_active:
                raise ValueError("Review owner unavailable")
            # Release every read transaction before provider execution. The
            # immutable input, not a locked ORM draft, crosses this boundary.
            await db.commit()

        async def verify():
            async with AsyncSessionLocal() as db:
                return await execute_approval_review(db, prepared, user_id)

        heartbeat = asyncio.create_task(renew(job_id, token))
        verification = asyncio.create_task(verify())
        done, _ = await asyncio.wait(
            {heartbeat, verification}, return_when=asyncio.FIRST_COMPLETED
        )
        if heartbeat in done:
            # A provider request may already be billed. Leave the lease for the
            # reaper and never schedule a second attempt automatically.
            heartbeat.result()
            raise RuntimeError("Review heartbeat stopped")
        result = verification.result()
        async with AsyncSessionLocal() as db:
            await leases.finish_review(
                db, job_id, token, status="verified", result=result
            )
    except HTTPException as exc:
        async with AsyncSessionLocal() as db:
            await leases.finish_review(
                db,
                job_id,
                token,
                status="rejected" if exc.status_code == 422 else "failed",
                error_code="unsupported_content"
                if exc.status_code == 422
                else "review_unavailable",
            )
    except ValueError:
        async with AsyncSessionLocal() as db:
            await leases.finish_review(
                db, job_id, token, status="failed", error_code="invalid_or_stale_input"
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        # Do not log source input/provider exception contents or replay an
        # ambiguous paid operation. Expiry makes it visible as interrupted.
        logger.warning("CV approval worker interrupted for job %s", job_id)
    finally:
        pending = [task for task in (heartbeat, verification) if task is not None]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


async def recovery_loop():
    active = {}
    try:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    await leases.interrupt_expired_reviews(db)
                    await db.commit()
                    ids = list(
                        (
                            await db.scalars(
                                select(CvApprovalJob.id)
                                .where(CvApprovalJob.status == "queued")
                                .order_by(CvApprovalJob.id)
                                .limit(leases.MAX_RUNNING_REVIEWS)
                            )
                        ).all()
                    )
                for job_id in list(active):
                    if active[job_id].done():
                        await asyncio.gather(active.pop(job_id), return_exceptions=True)
                for job_id in ids:
                    if (
                        job_id not in active
                        and len(active) < leases.MAX_RUNNING_REVIEWS
                    ):
                        active[job_id] = asyncio.create_task(execute_review_job(job_id))
            except Exception:
                logger.warning("CV approval recovery iteration unavailable")
            await asyncio.sleep(10)
    finally:
        for task in active.values():
            task.cancel()
        await asyncio.gather(*active.values(), return_exceptions=True)
