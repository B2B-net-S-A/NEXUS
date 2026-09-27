"""Runda 9 (R9-N3-5): zadanie przerwane przed wywołaniem modelu wraca do kolejki.

Deploy przerywał generację, a reaper od razu stawiał „interrupted”. Zadanie
bez zamrożonych faktów źródła nie doszło do płatnego wywołania, więc wraca do
kolejki; zadanie z faktami (wynik wywołania nieznany) jest przerywane jak
dotąd. Prawdziwy Postgres (CI) — predykat JSONB-null liczy baza.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.cv_generation_job import CvGenerationJob
from app.services.cv_generator_b2b.job_leases import (
    interrupt_expired_jobs,
    requeue_unstarted_expired_jobs,
)


async def test_expired_job_without_source_facts_is_requeued_not_interrupted():
    past = datetime.now(timezone.utc) - timedelta(minutes=5)
    marker = uuid.uuid4().hex

    def job(**extra) -> CvGenerationJob:
        return CvGenerationJob(
            kind="new",
            status="running",
            input_storage_key=f"synthetic/{marker}/{uuid.uuid4().hex}",
            input_sha256="0" * 64,
            lease_token=str(uuid.uuid4()),
            lease_expires_at=past,
            **extra,
        )

    unstarted = job()
    started = job(prepared_source_facts={"facts": "frozen"})
    ids: list[int] = []
    try:
        async with AsyncSessionLocal() as db:
            db.add_all([unstarted, started])
            await db.commit()
            ids = [unstarted.id, started.id]
        async with AsyncSessionLocal() as db:
            requeued = await requeue_unstarted_expired_jobs(db)
            interrupted = await interrupt_expired_jobs(db)
            await db.commit()
        assert unstarted.id in requeued and started.id not in requeued
        assert started.id in interrupted and unstarted.id not in interrupted
        async with AsyncSessionLocal() as db:
            rows = {
                row.id: row
                for row in (
                    await db.scalars(
                        select(CvGenerationJob).where(CvGenerationJob.id.in_(ids))
                    )
                ).all()
            }
        assert rows[unstarted.id].status == "queued"
        assert rows[unstarted.id].lease_token is None
        assert rows[started.id].status == "interrupted"
    finally:
        if ids:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(CvGenerationJob).where(CvGenerationJob.id.in_(ids))
                )
                await db.commit()
