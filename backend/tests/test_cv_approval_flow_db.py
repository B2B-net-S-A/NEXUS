"""Hosted PostgreSQL proof of queued review, unlocked editing and approval reuse.

The verifier and renderer are synthetic: these tests prove orchestration, not
real-model quality or DOCX appearance.
"""

import asyncio
from contextlib import asynccontextmanager
import hashlib
from threading import Event
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

from fastapi import HTTPException
import pytest
from sqlalchemy import delete, select
from app.core.database import AsyncSessionLocal
from app.models.user import User
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generated_draft import CvGeneratedDraft
from app.models.cv_approval_job import CvApprovalJob
from app.models.cv_document_version import CvDocumentVersion
from app.schemas.candidate_stage_cv import CVBrandedReview
from app.services import cv_approval_review as review
from app.services import cv_generated_editor as editor
from app.services.cv_approval_queue import enqueue_review
from app.services.cv_approval_worker import execute_review_job


@pytest.mark.parametrize("edit_during_review", [False, True])
async def test_durable_review_reuses_exact_result_and_does_not_lock_editor(
    monkeypatch, edit_during_review
):
    original = "<p>Reviewed source claim</p>"
    newer = "<p>Changed during verification</p>"
    started, release = Event(), Event()
    source = SimpleNamespace(
        cv_bytes=b"source",
        cv_filename="source.docx",
        screening_notes="",
        identity="",
        snapshot_sha256="a" * 64,
    )
    monkeypatch.setattr(review, "load_review_source", AsyncMock(return_value=source))
    monkeypatch.setattr(
        review, "extract_text_from_file", Mock(return_value="Source claim")
    )
    admissions = []

    @asynccontextmanager
    async def quota(*args, **kwargs):
        admissions.append(kwargs["user_id"])
        yield

    monkeypatch.setattr(review, "ai_feature", quota)

    def verify(content, **kwargs):
        assert content == original
        started.set()
        assert release.wait(timeout=15), "test did not release verifier"
        return {
            "version": review.VERIFIER_VERSION,
            "prompt_sha256": hashlib.sha256(
                review.VERIFICATION_PROMPT.encode()
            ).hexdigest(),
        }

    verifier = Mock(side_effect=verify)
    monkeypatch.setattr(review, "verify_editor_content", verifier)
    monkeypatch.setattr(editor, "render", AsyncMock(return_value=b"synthetic docx"))
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"review-flow-{uuid4()}@example.test", name="Synthetic review"
        )
        document = CvGeneratedDocument(
            candidate_name="Synthetic",
            filename="test.docx",
            mode="upload",
            status="ready",
        )
        db.add_all([user, document])
        await db.flush()
        draft = CvGeneratedDraft(
            generated_document_id=document.id,
            edit_revision=1,
            branded_draft_html=original,
            branded_template_content=b"template",
            branded_render_metadata={},
            branded_language="pl",
            branded_template="standard",
            branded_docx_filename="test.docx",
        )
        db.add(draft)
        await db.flush()
        user_id, document_id, draft_id = user.id, document.id, draft.id
        await db.commit()
    task = None
    try:
        payload = CVBrandedReview(
            expected_revision=1, content_html=original, request_key=uuid4()
        )
        async with AsyncSessionLocal() as db:
            draft = await db.get(CvGeneratedDraft, draft_id)
            queued = await enqueue_review(db, draft, payload, user_id)
            assert await enqueue_review(db, draft, payload, user_id) == queued
            await db.commit()
        assert admissions == []
        task = asyncio.create_task(execute_review_job(queued["review_id"]))
        assert await asyncio.wait_for(asyncio.to_thread(started.wait, 5), timeout=6)
        if edit_during_review:

            async def edit():
                async with AsyncSessionLocal() as db:
                    draft = await db.scalar(
                        select(CvGeneratedDraft)
                        .where(CvGeneratedDraft.id == draft_id)
                        .with_for_update()
                    )
                    editor.save(draft, 1, newer)
                    await db.commit()

            # Editing must finish while the model is still waiting.
            await asyncio.wait_for(edit(), timeout=3)
        release.set()
        await asyncio.wait_for(task, timeout=6)
        async with AsyncSessionLocal() as db:
            job = await db.get(CvApprovalJob, queued["review_id"])
            assert job.status == "verified"
            assert job.input_content is None
            draft = await db.scalar(
                select(CvGeneratedDraft)
                .where(CvGeneratedDraft.id == draft_id)
                .with_for_update()
            )
            if edit_during_review:
                with pytest.raises(HTTPException) as error:
                    await editor.finalize(db, draft, 2, newer, user_id)
                assert error.value.detail["code"] == "cv_review_required"
                assert draft.branded_status == "draft"
                assert (
                    await db.scalar(
                        select(CvDocumentVersion.id).where(
                            CvDocumentVersion.generated_owner_id == document_id
                        )
                    )
                    is None
                )
                await db.rollback()
            else:
                version = await editor.finalize(db, draft, 1, original, user_id)
                assert version.content_html == original
                assert version.render_metadata["content_review"]["reused"] is True
                await db.commit()
        verifier.assert_called_once()
        assert admissions == [user_id]
    finally:
        release.set()
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvGeneratedDocument).where(CvGeneratedDocument.id == document_id)
            )
            await db.execute(delete(User).where(User.id == user_id))
            await db.commit()
