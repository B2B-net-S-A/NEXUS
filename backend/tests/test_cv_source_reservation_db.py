"""Real PostgreSQL commit/rollback boundary for pre-upload recovery intent."""

from unittest.mock import Mock
from datetime import datetime, timedelta
import asyncio

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_source_cleanup import CvSourceCleanup
from app.services.cv_generator_b2b import durable_jobs as jobs
from app.services import cv_source_cleanup as source_cleanup


@pytest.mark.parametrize("commit_job", [False, True])
async def test_upload_reservation_survives_only_uncommitted_job(
    monkeypatch, commit_job
):
    upload = Mock()
    remove = Mock()
    monkeypatch.setattr(jobs.object_storage, "upload_cv", upload)
    monkeypatch.setattr(jobs.object_storage, "delete_cv", remove)
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

            class AfterRetention(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime.now(tz) + timedelta(days=2)

            monkeypatch.setattr(source_cleanup, "datetime", AfterRetention)
            async with AsyncSessionLocal() as cleaner:
                # A due reservation must be skipped, not blocked on or deleted,
                # while the owner's commit outcome remains unknown.
                await asyncio.wait_for(source_cleanup.clean_pending_sources(cleaner), 3)
            remove.assert_not_called()
            if commit_job:
                await db.commit()
            else:
                await db.rollback()
        async with AsyncSessionLocal() as observer:
            assert (await observer.get(CvSourceCleanup, key) is None) == commit_job
            assert (
                await observer.get(CvGeneratedDocument, document_id) is not None
            ) == commit_job
            await source_cleanup.clean_pending_sources(observer)
            if commit_job:
                remove.assert_not_called()
            else:
                remove.assert_called_once_with(key)
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
