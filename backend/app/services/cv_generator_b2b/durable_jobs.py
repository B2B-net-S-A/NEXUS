"""Persisted CV inputs and a database-claimed background executor."""

import asyncio
from datetime import date
from contextlib import suppress
import logging

from fastapi import HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.database import AsyncSessionLocal
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.services import object_storage
from app.services.ai_quota import QuotaState
from app.services.cv_generator_b2b.job_leases import (
    claim_job,
    finish_job,
    heartbeat_job,
    owned_job,
    lock_owned_job,
)
from app.services.cv_generator_b2b.job_snapshot import (
    deserialize_job_inputs,
    serialize_job_inputs,
)

logger = logging.getLogger(__name__)


async def persist_job(
    db,
    *,
    kind: str,
    user_id: int,
    inputs: dict,
    generated_id: int | None = None,
    preview_id: int | None = None,
    charge=None,
) -> int:
    """Caller commits job and result placeholder together, before scheduling."""
    if (kind == "preview") != (preview_id is not None) or (
        (generated_id is None) == (preview_id is None)
    ):
        raise ValueError("CV job must reference exactly its result type")
    raw, digest = serialize_job_inputs(kind, inputs)
    try:
        key = await run_in_threadpool(
            object_storage.upload_cv, raw, "cv-job-input.json", "application/json"
        )
    except Exception as exc:
        raise HTTPException(
            503,
            "Nie udało się zapisać wejścia generacji. Limit AI nie został naliczony.",
        ) from exc
    try:
        quota = await charge() if charge is not None else None
    except Exception:
        # This fresh object has never been referenced by a committed job.
        try:
            await run_in_threadpool(object_storage.delete_cv, key)
        except Exception:
            logger.exception("Could not remove rejected CV input snapshot")
        raise
    quota_snapshot = (
        None
        if quota is None
        else {
            "used": quota.used,
            "limit": quota.limit,
            "period_start": quota.period_start.isoformat(),
            "operation_id": quota.operation_id,
        }
    )
    job = CvGenerationJob(
        generated_id=generated_id,
        preview_id=preview_id,
        created_by=user_id,
        kind=kind,
        status="queued",
        input_storage_key=key,
        input_sha256=digest,
        quota_snapshot=quota_snapshot,
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
        preview_id = job.preview_id
        quota_snapshot = job.quota_snapshot
    renewal = asyncio.create_task(_renew(job_id, token))
    work = None
    failed = False
    try:
        raw = await run_in_threadpool(object_storage.download_cv, key)
        stored_kind, inputs = deserialize_job_inputs(raw, digest)
        if stored_kind != kind or kind not in {"new", "upload", "preview"}:
            raise ValueError("CV job kind mismatch")
        if quota_snapshot is not None:
            inputs["quota_state"] = QuotaState(
                used=quota_snapshot["used"],
                limit=quota_snapshot["limit"],
                period_start=date.fromisoformat(quota_snapshot["period_start"]),
                operation_id=quota_snapshot["operation_id"],
            )
        with owned_job(job_id, token):
            async with AsyncSessionLocal() as db:
                await lock_owned_job(db)
                await db.commit()
            if kind == "preview":
                from app.api.client_cv_rules import _run_rule_preview_job

                work = asyncio.create_task(_run_rule_preview_job(preview_id, **inputs))
            else:
                worker = (
                    _run_generate_new_job if kind == "new" else _run_generate_upload_job
                )
                work = asyncio.create_task(
                    _run_declared(worker, generated_id, **inputs)
                )
        done, _ = await asyncio.wait(
            {work, renewal}, return_when=asyncio.FIRST_COMPLETED
        )
        if renewal in done:
            await renewal  # Surface loss before accepting a result.
        await work
        async with AsyncSessionLocal() as db:
            document = await db.get(
                ClientCvRulePreview if kind == "preview" else CvGeneratedDocument,
                preview_id if kind == "preview" else generated_id,
            )
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
            # Update every unfinished result, including a second language, only
            # while this attempt still owns the lease. Otherwise the reaper owns it.
            with owned_job(job_id, token):
                try:
                    await lock_owned_job(db)
                except RuntimeError:
                    await db.rollback()
                else:
                    await fail_unfinished_outputs(db, job_id)
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
                        previews = select(CvGenerationJob.preview_id).where(
                            CvGenerationJob.id.in_(expired)
                        )
                        await db.execute(
                            update(ClientCvRulePreview)
                            .where(
                                ClientCvRulePreview.id.in_(previews),
                                ClientCvRulePreview.status == "processing",
                            )
                            .values(
                                status="failed",
                                error_message="CV próbne przerwane po utracie wykonawcy. Uruchom ponownie po sprawdzeniu wyniku.",
                            )
                        )
                    await db.commit()
                finished = {task for task in active if task.done()}
                for task in finished:
                    try:
                        task.result()
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        logger.exception("CV recovered task exited unexpectedly")
                active -= finished
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


async def fail_unfinished_outputs(db, job_id: int):
    """Preserve ready artifacts while terminating all unfinished outputs."""
    from sqlalchemy import update

    outputs = (
        select(CvGenerationJob.generated_id)
        .where(CvGenerationJob.id == job_id)
        .union(
            select(CvGenerationJob.second_generated_id).where(
                CvGenerationJob.id == job_id
            )
        )
    )
    await db.execute(
        update(CvGeneratedDocument)
        .where(
            CvGeneratedDocument.id.in_(outputs),
            CvGeneratedDocument.status == "processing",
        )
        .values(
            status="failed",
            error_message="Generacja przerwana. Sprawdź wynik przed ponowieniem.",
        )
    )
    previews = select(CvGenerationJob.preview_id).where(CvGenerationJob.id == job_id)
    await db.execute(
        update(ClientCvRulePreview)
        .where(
            ClientCvRulePreview.id.in_(previews),
            ClientCvRulePreview.status == "processing",
        )
        .values(
            status="failed", error_message="Generacja CV próbnego została przerwana."
        )
    )
