"""Real row-lock contention must not leave candidate erasure waiting on a worker."""

import asyncio
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.services.cv_source_erasure import detach_candidate_job_sources


async def test_locked_source_job_rejects_erasure_then_allows_retry():
    async with AsyncSessionLocal() as seed:
        candidate = Candidate(
            name="Synthetic", lastname="Erasure", email=f"{uuid4()}@example.test"
        )
        seed.add(candidate)
        await seed.flush()
        document = CvGeneratedDocument(
            candidate_id=candidate.id,
            candidate_name="Synthetic Erasure",
            filename="synthetic.docx",
            mode="new",
            status="ready",
        )
        seed.add(document)
        await seed.flush()
        job = CvGenerationJob(
            generated_id=document.id,
            kind="new",
            status="complete",
            input_storage_key="synthetic-lock-source",
            input_sha256="a" * 64,
        )
        seed.add(job)
        await seed.commit()
        candidate_id, document_id, job_id = candidate.id, document.id, job.id
    try:
        async with AsyncSessionLocal() as worker, AsyncSessionLocal() as eraser:
            try:
                await worker.scalar(
                    select(CvGenerationJob)
                    .where(CvGenerationJob.id == job_id)
                    .with_for_update()
                )
                await eraser.scalar(
                    select(Candidate)
                    .where(Candidate.id == candidate_id)
                    .with_for_update()
                )
                with pytest.raises(HTTPException) as error:
                    await asyncio.wait_for(
                        detach_candidate_job_sources(eraser, candidate_id), timeout=3
                    )
                assert error.value.status_code == 409
            finally:
                await eraser.rollback()
                await worker.rollback()
        async with AsyncSessionLocal() as retry:
            try:
                assert await retry.get(Candidate, candidate_id) is not None
                assert await retry.get(CvGenerationJob, job_id) is not None
                await retry.scalar(
                    select(Candidate)
                    .where(Candidate.id == candidate_id)
                    .with_for_update()
                )
                assert await detach_candidate_job_sources(retry, candidate_id) == [
                    "synthetic-lock-source"
                ]
                await retry.flush()
                assert await retry.get(CvGenerationJob, job_id) is None
            finally:
                await retry.rollback()
    finally:
        async with AsyncSessionLocal() as cleanup:
            await cleanup.execute(
                delete(CvGeneratedDocument).where(CvGeneratedDocument.id == document_id)
            )
            await cleanup.execute(delete(Candidate).where(Candidate.id == candidate_id))
            await cleanup.commit()


async def test_active_review_blocks_erasure_and_terminal_review_source_is_removed():
    from tests.test_cv_approval_leases import review_jobs
    from app.models.cv_approval_job import CvApprovalJob
    from app.services.cv_approval_leases import cancel_review
    from sqlalchemy import update

    async with review_jobs() as (review_id,):
        async with AsyncSessionLocal() as db:
            candidate = Candidate(
                name="Synthetic",
                lastname="Review erasure",
                email=f"{uuid4()}@example.test",
            )
            db.add(candidate)
            await db.flush()
            candidate_id = candidate.id
            review = await db.get(CvApprovalJob, review_id)
            await db.execute(
                update(CvGeneratedDocument)
                .where(CvGeneratedDocument.id == review.generated_document_id)
                .values(candidate_id=candidate_id)
            )
            await db.commit()
        try:
            async with AsyncSessionLocal() as db:
                await db.scalar(
                    select(Candidate)
                    .where(Candidate.id == candidate_id)
                    .with_for_update()
                )
                with pytest.raises(HTTPException) as error:
                    await detach_candidate_job_sources(db, candidate_id)
                assert error.value.status_code == 409
                await db.rollback()
                assert await cancel_review(db, review_id)
                await db.commit()
                await db.scalar(
                    select(Candidate)
                    .where(Candidate.id == candidate_id)
                    .with_for_update()
                )
                assert await detach_candidate_job_sources(db, candidate_id) == []
                await db.flush()
                assert await db.get(CvApprovalJob, review_id) is None
                await db.commit()
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
                await db.commit()
