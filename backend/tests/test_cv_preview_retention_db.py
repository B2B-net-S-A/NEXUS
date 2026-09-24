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


async def test_sweep_without_client_retires_old_previews_of_every_client():
    """Generator v3: CV próbnych nie da się już zlecić, więc retencja nie może
    czekać na „kolejny podgląd tego klienta" — pętla `cv_source_cleanup` woła
    ją dla WSZYSTKICH klientów (`client_id=None`). Świeży podgląd zostaje."""
    from app.services.cv_preview_retention import PREVIEW_RETENTION

    client_ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            previews = []
            for age in (timedelta(days=3650), timedelta(days=3649), timedelta(days=1)):
                client = Client(
                    name=f"Retention sweep {uuid4().hex}",
                    status=ClientStatus.active,
                    hidden=False,
                )
                db.add(client)
                await db.flush()
                client_ids.append(client.id)
                preview = ClientCvRulePreview(
                    client_id=client.id,
                    status="ready",
                    language="pl",
                    created_at=datetime.now(timezone.utc) - age,
                )
                db.add(preview)
                await db.flush()
                previews.append(preview.id)
            await db.commit()
        old_a, old_b, fresh = previews
        async with AsyncSessionLocal() as db:
            await retire_previews(
                db, None, datetime.now(timezone.utc) - PREVIEW_RETENTION
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await db.get(ClientCvRulePreview, old_a) is None
            assert await db.get(ClientCvRulePreview, old_b) is None
            assert await db.get(ClientCvRulePreview, fresh) is not None
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientCvRulePreview).where(
                    ClientCvRulePreview.client_id.in_(client_ids)
                )
            )
            await db.execute(delete(Client).where(Client.id.in_(client_ids)))
            await db.commit()


async def test_cleanup_loop_runs_the_preview_sweep_for_all_clients():
    import inspect

    from app.services import cv_source_cleanup

    source = inspect.getsource(cv_source_cleanup.recovery_loop)
    assert "retire_previews" in source
    assert "db, None, datetime.now(timezone.utc) - PREVIEW_RETENTION" in source
