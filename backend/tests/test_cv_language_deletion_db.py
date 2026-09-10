"""PostgreSQL proof that deleting one language preserves the shared source job."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import select

from app.api import cv_generator_b2b as api
from app.core.database import AsyncSessionLocal
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.models.cv_source_cleanup import CvSourceCleanup


@pytest.mark.parametrize("delete_primary", [True, False])
async def test_surviving_language_keeps_source_job_after_parent_delete(
    monkeypatch, delete_primary
):
    async with AsyncSessionLocal() as db:
        try:
            documents = [
                CvGeneratedDocument(
                    candidate_name="Synthetic deletion fixture",
                    filename=f"synthetic-{language}.docx",
                    mode="upload",
                    status="ready",
                )
                for language in ("pl", "en")
            ]
            db.add_all(documents)
            await db.flush()
            primary, secondary = documents
            job = CvGenerationJob(
                generated_id=primary.id,
                second_generated_id=secondary.id,
                kind="upload",
                status="complete",
                input_storage_key="synthetic-unused-source-key",
                input_sha256="a" * 64,
            )
            db.add(job)
            await db.flush()
            job_id = job.id
            removed, survivor = (
                (primary, secondary) if delete_primary else (secondary, primary)
            )
            removed_id, survivor_id = removed.id, survivor.id
            monkeypatch.setattr(
                api, "_load_generated_document", AsyncMock(return_value=removed)
            )
            # Exercise real flush/FK behavior while keeping all fixtures rollback-only.
            monkeypatch.setattr(db, "commit", db.flush)
            user = SimpleNamespace(id=7, has_role=Mock(return_value=True))
            result = await api.delete_generated_cv(removed_id, user, db)
            assert result.status_code == 204
            db.expunge_all()
            assert await db.get(CvGeneratedDocument, removed_id) is None
            assert await db.get(CvGeneratedDocument, survivor_id) is not None
            retained = await db.scalar(
                select(CvGenerationJob).where(
                    (CvGenerationJob.generated_id == survivor_id)
                    | (CvGenerationJob.second_generated_id == survivor_id)
                )
            )
            assert retained is not None
            assert retained.id == job_id
            assert retained.input_storage_key == "synthetic-unused-source-key"
            assert retained.input_sha256 == "a" * 64
            assert retained.generated_id == survivor_id
            assert retained.second_generated_id is None
            assert await db.get(CvSourceCleanup, retained.input_storage_key) is None

            # Only the final language deletion schedules storage cleanup, in the
            # same transaction as the cascading removal of its source job.
            survivor_row = await db.get(CvGeneratedDocument, survivor_id)
            monkeypatch.setattr(
                api, "_load_generated_document", AsyncMock(return_value=survivor_row)
            )
            await api.delete_generated_cv(survivor_id, user, db)
            db.expunge_all()
            assert await db.get(CvGenerationJob, job_id) is None
            assert (
                await db.get(CvSourceCleanup, "synthetic-unused-source-key") is not None
            )
        finally:
            await db.rollback()

        # Rolling back document removal also rolls back its deletion intent.
        assert await db.get(CvSourceCleanup, "synthetic-unused-source-key") is None
