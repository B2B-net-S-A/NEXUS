"""Real PostgreSQL commit/rollback boundary for pre-upload recovery intent."""

from unittest.mock import Mock

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_source_cleanup import CvSourceCleanup
from app.services.cv_generator_b2b import durable_jobs as jobs


@pytest.mark.parametrize("commit_job", [False, True])
async def test_upload_reservation_survives_only_uncommitted_job(
    monkeypatch, commit_job
):
    upload = Mock()
    monkeypatch.setattr(jobs.object_storage, "upload_cv", upload)
    key = None
    document_id = None
    try:
        async with AsyncSessionLocal() as db:
            document = CvGeneratedDocument(
                candidate_name="Synthetic reservation",
                filename="test.docx",
                mode="upload",
                status="processing",
            )
            db.add(document)
            await db.flush()
            document_id = document.id
            await jobs.persist_job(
                db, kind="upload", user_id=None, inputs={}, generated_id=document.id
            )
            key = upload.call_args.kwargs["storage_key"]
            # The independent recovery record is committed before object upload,
            # and stays visible until the owning job's transaction commits.
            async with AsyncSessionLocal() as observer:
                assert await observer.get(CvSourceCleanup, key) is not None
            if commit_job:
                await db.commit()
            else:
                await db.rollback()
        async with AsyncSessionLocal() as observer:
            assert (await observer.get(CvSourceCleanup, key) is None) == commit_job
            assert (
                await observer.get(CvGeneratedDocument, document_id) is not None
            ) == commit_job
    finally:
        async with AsyncSessionLocal() as cleanup:
            if key:
                await cleanup.execute(
                    delete(CvSourceCleanup).where(CvSourceCleanup.storage_key == key)
                )
            if document_id:
                await cleanup.execute(
                    delete(CvGeneratedDocument).where(
                        CvGeneratedDocument.id == document_id
                    )
                )
            await cleanup.commit()
