"""Hosted PostgreSQL races for durable approval reviews."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, update
from app.core.database import AsyncSessionLocal
from app.models.cv_approval_job import CvApprovalJob
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generated_draft import CvGeneratedDraft
from app.services import cv_approval_leases as leases


@asynccontextmanager
async def review_jobs(count=1):
    async with AsyncSessionLocal() as db:
        doc = CvGeneratedDocument(
            candidate_name="Synthetic",
            filename="test.docx",
            mode="upload",
            status="ready",
        )
        db.add(doc)
        await db.flush()
        draft = CvGeneratedDraft(
            generated_document_id=doc.id,
            branded_draft_html="<p>Source</p>",
            branded_template_content=b"template",
            branded_render_metadata={},
            branded_language="pl",
            branded_template="standard",
            branded_docx_filename="test.docx",
        )
        db.add(draft)
        await db.flush()
        jobs = [
            CvApprovalJob(
                generated_document_id=doc.id,
                generated_draft_id=draft.id,
                request_key=str(uuid4()),
                request_sha256="a" * 64,
                expected_revision=0,
                input_sha256="b" * 64,
                input_content=b"private source",
                status="queued",
            )
            for _ in range(count)
        ]
        db.add_all(jobs)
        await db.flush()
        ids, document_id = [job.id for job in jobs], doc.id
        await db.commit()
    try:
        yield ids
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvGeneratedDocument).where(CvGeneratedDocument.id == document_id)
            )
            await db.commit()


async def test_review_has_one_owner_and_expiry_prevents_paid_replay():
    async with review_jobs() as (job_id,):

        async def claim():
            async with AsyncSessionLocal() as db:
                return await leases.claim_review(db, job_id)

        tokens = [token for token in await asyncio.gather(claim(), claim()) if token]
        assert len(tokens) == 1
        token = tokens[0]
        async with AsyncSessionLocal() as db:
            assert not await leases.heartbeat_review(db, job_id, "wrong-owner")
            assert await leases.heartbeat_review(db, job_id, token)
            await db.execute(
                update(CvApprovalJob)
                .where(CvApprovalJob.id == job_id)
                .values(
                    lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)
                )
            )
            await db.commit()
            assert not await leases.finish_review(
                db, job_id, token, status="verified", result={"status": "verified"}
            )
            assert not await leases.heartbeat_review(db, job_id, token)
            assert job_id in await leases.interrupt_expired_reviews(db)
            await db.commit()
            assert await leases.claim_review(db, job_id) is None
            job = await db.get(CvApprovalJob, job_id)
            assert job.status == "interrupted"
            assert job.input_content is None
            assert job.result is None


async def test_review_capacity_is_shared_between_concurrent_claims():
    async with review_jobs(leases.MAX_RUNNING_REVIEWS + 1) as ids:

        async def claim(job_id):
            async with AsyncSessionLocal() as db:
                return job_id, await leases.claim_review(db, job_id)

        attempts = await asyncio.gather(*(claim(job_id) for job_id in ids))
        active = [(job_id, token) for job_id, token in attempts if token]
        queued = [job_id for job_id, token in attempts if not token]
        assert len(active) == leases.MAX_RUNNING_REVIEWS
        assert len(queued) == 1
        async with AsyncSessionLocal() as db:
            assert await leases.finish_review(
                db, *active[0], status="failed", error_code="synthetic_failure"
            )
            assert await leases.claim_review(db, queued[0]) is not None


async def test_cancel_fences_worker_and_preserves_terminal_evidence():
    async with review_jobs(2) as (cancelled, completed):
        async with AsyncSessionLocal() as db:
            token = await leases.claim_review(db, cancelled)
            assert token
            assert await leases.cancel_review(db, cancelled)
            await db.commit()
            assert not await leases.finish_review(
                db, cancelled, token, status="verified", result={"status": "verified"}
            )
            assert await leases.claim_review(db, cancelled) is None
            other = await leases.claim_review(db, completed)
            assert other
            evidence = {"status": "verified", "html_sha256": "c" * 64}
            assert await leases.finish_review(
                db, completed, other, status="verified", result=evidence
            )
            assert not await leases.cancel_review(db, completed)
            await db.commit()
            job = await db.get(CvApprovalJob, completed)
            assert job.result == evidence
            assert job.input_content is None


@pytest.mark.parametrize(
    "status,result",
    [("queued", None), ("verified", None), ("verified", {"status": "failed"})],
)
async def test_invalid_completion_never_touches_database(status, result):
    db = AsyncMock()
    with pytest.raises(ValueError):
        await leases.finish_review(db, 1, "token", status=status, result=result)
    db.scalar.assert_not_awaited()
    db.commit.assert_not_awaited()
