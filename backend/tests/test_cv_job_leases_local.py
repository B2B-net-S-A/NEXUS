"""Host-native state transitions; PostgreSQL concurrency has separate CI coverage."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, insert, select, update

from app.models.cv_generation_job import CvGenerationJob
from app.services.cv_generator_b2b.job_leases import (
    claim_job,
    finish_job,
    heartbeat_job,
    interrupt_expired_jobs,
)


class SessionAdapter:
    def __init__(self, connection):
        self.connection = connection

    async def execute(self, statement):
        return self.connection.execute(statement)

    async def commit(self):
        self.connection.commit()


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    # SQLite foreign keys are intentionally not enabled: these tests create only
    # attempt rows; production foreign keys are exercised against PostgreSQL.
    CvGenerationJob.__table__.create(engine)
    with engine.connect() as connection:
        yield SessionAdapter(connection)
    engine.dispose()


async def test_attempt_cannot_be_claimed_twice_or_finished_by_another_owner(session):
    result = await session.execute(
        insert(CvGenerationJob)
        .values(
            kind="upload",
            status="queued",
            input_storage_key="test-only",
            input_sha256="a" * 64,
        )
        .returning(CvGenerationJob.id)
    )
    job_id = result.scalar_one()
    await session.commit()
    owner = await claim_job(session, job_id)
    assert owner
    assert await claim_job(session, job_id) is None
    assert not await finish_job(session, job_id, "other-owner")
    assert await heartbeat_job(session, job_id, owner)
    assert await finish_job(session, job_id, owner)
    assert await claim_job(session, job_id) is None
    assert not await heartbeat_job(session, job_id, owner)


async def test_expired_work_is_interrupted_not_requeued(session):
    result = await session.execute(
        insert(CvGenerationJob)
        .values(
            kind="new",
            status="queued",
            input_storage_key="test-only",
            input_sha256="b" * 64,
        )
        .returning(CvGenerationJob.id)
    )
    job_id = result.scalar_one()
    await session.commit()
    owner = await claim_job(session, job_id)
    await session.execute(
        update(CvGenerationJob)
        .where(CvGenerationJob.id == job_id)
        .values(
            lease_expires_at=datetime.now(timezone.utc) - timedelta(seconds=1),
        )
    )
    await session.commit()
    assert not await heartbeat_job(session, job_id, owner)
    assert await interrupt_expired_jobs(session) == [job_id]
    await session.commit()
    assert not await finish_job(session, job_id, owner)
    assert await claim_job(session, job_id) is None
    row = (
        await session.execute(
            select(CvGenerationJob.status, CvGenerationJob.error_code).where(
                CvGenerationJob.id == job_id
            )
        )
    ).one()
    assert row == ("interrupted", "worker_lease_expired")
