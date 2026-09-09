"""Persisted CV inputs and a database-claimed background executor."""

import asyncio
from contextlib import suppress
import logging

from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.database import AsyncSessionLocal
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.services import object_storage
from app.services.cv_generator_b2b.job_leases import (
    claim_job,
    finish_job,
    heartbeat_job,
    owned_job,
)
from app.services.cv_generator_b2b.job_snapshot import (
    deserialize_job_inputs,
    serialize_job_inputs,
)

logger = logging.getLogger(__name__)


async def persist_job(
    db, *, generated_id: int, kind: str, user_id: int, inputs: dict
) -> int:
    """Caller commits job and result placeholder together, before scheduling."""
    raw, digest = serialize_job_inputs(kind, inputs)
    key = await run_in_threadpool(
        object_storage.upload_cv, raw, "cv-job-input.json", "application/json"
    )
    job = CvGenerationJob(
        generated_id=generated_id,
        created_by=user_id,
        kind=kind,
        status="queued",
        input_storage_key=key,
        input_sha256=digest,
    )
    db.add(job)
    await db.flush()
    return job.id


async def _renew(job_id: int, token: str):
    while True:
        await asyncio.sleep(30)
        async with AsyncSessionLocal() as db:
            if not await heartbeat_job(db, job_id, token):
                raise RuntimeError("CV job lease lost")


async def execute_job(job_id: int):
    # Imported lazily: API admission uses persist_job from this module.
    from app.api.cv_generator_b2b import (
        _run_declared,
        _run_generate_new_job,
        _run_generate_upload_job,
    )

    async with AsyncSessionLocal() as db:
        token = await claim_job(db, job_id)
        if token is None:
            return
        job = await db.get(CvGenerationJob, job_id)
        key, digest, generated_id, kind = (
            job.input_storage_key,
            job.input_sha256,
            job.generated_id,
            job.kind,
        )
    renewal = asyncio.create_task(_renew(job_id, token))
    work = None
    failed = False
    try:
        raw = await run_in_threadpool(object_storage.download_cv, key)
        stored_kind, inputs = deserialize_job_inputs(raw, digest)
        if stored_kind != kind or kind not in {"new", "upload"}:
            raise ValueError("CV job kind mismatch")
        worker = _run_generate_new_job if kind == "new" else _run_generate_upload_job
        with owned_job(job_id, token):
            work = asyncio.create_task(_run_declared(worker, generated_id, **inputs))
        done, _ = await asyncio.wait(
            {work, renewal}, return_when=asyncio.FIRST_COMPLETED
        )
        if renewal in done:
            await renewal  # Surface loss before accepting a result.
        await work
        async with AsyncSessionLocal() as db:
            document = await db.get(CvGeneratedDocument, generated_id)
            job = await db.get(CvGenerationJob, job_id)
            second = (
                await db.get(CvGeneratedDocument, job.second_generated_id)
                if job.second_generated_id
                else None
            )
            failed = (
                document is None
                or document.status != "ready"
                or (second is not None and second.status != "ready")
            )
    except asyncio.CancelledError:
        # Leave running lease for the reaper: outcome of a provider call is unknown.
        raise
    except Exception:
        failed = True
        logger.exception("CV durable job failed: id=%s", job_id)
        async with AsyncSessionLocal() as db:
            document = await db.get(CvGeneratedDocument, generated_id)
            if document is not None and document.status == "processing":
                document.status = "failed"
                document.error_message = (
                    "Generacja przerwana. Sprawdź wynik przed ponowieniem."
                )
                await db.commit()
    finally:
        for task in (work, renewal):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
    async with AsyncSessionLocal() as db:
        await finish_job(db, job_id, token, failed=failed)


async def queued_job_ids(limit: int = 4) -> list[int]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(
                    select(CvGenerationJob.id)
                    .where(CvGenerationJob.status == "queued")
                    .order_by(CvGenerationJob.id)
                    .limit(limit)
                )
            ).all()
        )


async def recovery_loop():
    """Resume only never-started jobs; fence expired work without paid replay."""
    from sqlalchemy import update
    from app.services.cv_generator_b2b.job_leases import interrupt_expired_jobs

    active = set()
    try:
        while True:
            try:
                async with AsyncSessionLocal() as db:
                    expired = await interrupt_expired_jobs(db)
                    if expired:
                        documents = (
                            select(CvGenerationJob.generated_id)
                            .where(CvGenerationJob.id.in_(expired))
                            .union(
                                select(CvGenerationJob.second_generated_id).where(
                                    CvGenerationJob.id.in_(expired)
                                )
                            )
                        )
                        await db.execute(
                            update(CvGeneratedDocument)
                            .where(
                                CvGeneratedDocument.id.in_(documents),
                                CvGeneratedDocument.status == "processing",
                            )
                            .values(
                                status="failed",
                                error_message="Generacja przerwana po utracie wykonawcy. Sprawdź wynik przed ponowieniem.",
                            )
                        )
                    await db.commit()
                active = {task for task in active if not task.done()}
                if len(active) < 4:
                    for job_id in await queued_job_ids(4 - len(active)):
                        task = asyncio.create_task(execute_job(job_id))
                        active.add(task)
            except Exception:
                logger.exception("CV job recovery iteration failed")
            await asyncio.sleep(10)
    finally:
        for task in active:
            task.cancel()
        await asyncio.gather(*active, return_exceptions=True)
