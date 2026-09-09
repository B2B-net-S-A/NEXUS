"""Hosted PostgreSQL proof that queued work and its admission share a transaction."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.ai_metering import AIOperation
from app.models.cv_generation_job import CvGenerationJob
from app.services import ai_quota


@pytest.mark.parametrize("commit", [False, True])
async def test_admission_and_job_commit_or_rollback_together(monkeypatch, commit):
    monkeypatch.setattr(ai_quota, "get_master_enabled", AsyncMock(return_value=True))
    monkeypatch.setattr(
        ai_quota,
        "get_feature_config",
        AsyncMock(return_value=SimpleNamespace(enabled=True, monthly_limit=10)),
    )
    monkeypatch.setattr(
        ai_quota, "get_total_usage_for_period", AsyncMock(return_value=0)
    )
    async with AsyncSessionLocal() as db:
        state = await ai_quota.check_and_increment(
            db, AIFeatureKey.cv_generator, commit_with_caller=True
        )
        job = CvGenerationJob(
            kind="upload",
            status="queued",
            input_storage_key="test-only/atomic",
            input_sha256="e" * 64,
            quota_snapshot={"operation_id": state.operation_id},
        )
        db.add(job)
        await db.flush()
        job_id = job.id
        if commit:
            await db.commit()
        else:
            await db.rollback()
    try:
        async with AsyncSessionLocal() as db:
            assert (await db.get(AIOperation, state.operation_id) is not None) is commit
            assert (await db.get(CvGenerationJob, job_id) is not None) is commit
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CvGenerationJob).where(CvGenerationJob.id == job_id)
            )
            await db.execute(
                delete(AIOperation).where(AIOperation.id == state.operation_id)
            )
            await db.commit()
