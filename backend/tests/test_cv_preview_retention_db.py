"""Real PostgreSQL retention must preserve the source until deletion commits."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.client import Client, ClientStatus
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generation_job import CvGenerationJob
from app.models.cv_source_cleanup import CvSourceCleanup
from app.services.cv_preview_retention import retire_previews


@pytest.mark.parametrize("commit", [False, True])
async def test_preview_source_cleanup_commits_with_owner_deletion(commit):
    client_id = None
    key = f"synthetic-retention/{uuid4().hex}"
    try:
        async with AsyncSessionLocal() as db:
            client = Client(
                name=f"Retention {uuid4().hex}",
                status=ClientStatus.active,
                hidden=False,
            )
            db.add(client)
            await db.flush()
            client_id = client.id
            preview = ClientCvRulePreview(
                client_id=client_id,
                status="ready",
                language="pl",
                created_at=datetime.now(timezone.utc) - timedelta(days=60),
            )
            db.add(preview)
            await db.flush()
            preview_id = preview.id
            job = CvGenerationJob(
                preview_id=preview_id,
                kind="preview",
                status="complete",
                input_storage_key=key,
                input_sha256="a" * 64,
            )
            db.add(job)
            await db.commit()
            job_id = job.id
        async with AsyncSessionLocal() as db:
            await retire_previews(db, client_id, datetime.now(timezone.utc))
            await db.flush()
            async with AsyncSessionLocal() as observer:
                assert await observer.get(ClientCvRulePreview, preview_id) is not None
                assert await observer.get(CvSourceCleanup, key) is None
            if commit:
                await db.commit()
            else:
                await db.rollback()
        async with AsyncSessionLocal() as db:
            assert (await db.get(ClientCvRulePreview, preview_id) is None) == commit
            assert (await db.get(CvGenerationJob, job_id) is None) == commit
            assert (await db.get(CvSourceCleanup, key) is not None) == commit
    finally:
        async with AsyncSessionLocal() as db:
            if client_id is not None:
                await db.execute(delete(Client).where(Client.id == client_id))
            await db.execute(
                delete(CvSourceCleanup).where(CvSourceCleanup.storage_key == key)
            )
            await db.commit()
