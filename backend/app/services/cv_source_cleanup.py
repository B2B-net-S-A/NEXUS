"""Retry source deletion only for committed, explicitly removed document owners."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging
import time

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client_cv_rule_preview import ClientCvRulePreview
from app.models.cv_generated_document import CvGeneratedDocument
from app.models.cv_generation_job import CvGenerationJob
from app.models.cv_source_cleanup import CvSourceCleanup
from app.services import object_storage

logger = logging.getLogger(__name__)

# `cv_generation_jobs.input_storage_key` is NOT NULL, so a job whose private
# input has been retired points here instead. Real keys start with "cv/"; this
# can never name a stored object, and it marks the row as already swept.
PURGED_KEY_PREFIX = "purged/"
# The retention sweep is a handful of indexed rows a day — no need to run it
# on every 30-second tick of the deletion loop.
RETENTION_INTERVAL_SECONDS = 15 * 60


def is_purged_key(storage_key: str | None) -> bool:
    return bool(storage_key) and storage_key.startswith(PURGED_KEY_PREFIX)


async def reserve_source_key(db) -> str:
    """Commit recovery intent before upload; caller locks it until job commit."""
    key = object_storage.new_cv_storage_key("cv-job-input.json")
    async with AsyncSessionLocal() as reservation_db:
        await reservation_db.execute(
            insert(CvSourceCleanup).values(
                storage_key=key,
                attempts=0,
                next_attempt_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        await reservation_db.commit()
    intent = await db.scalar(
        select(CvSourceCleanup)
        .where(CvSourceCleanup.storage_key == key)
        .with_for_update()
    )
    if intent is None:
        raise RuntimeError("Source reservation expired before upload")
    return key


async def schedule_source_cleanup(db, storage_key: str):
    """Caller commits this intent with the deletion. Never touch storage here."""
    if storage_key and not is_purged_key(storage_key):
        await db.execute(
            insert(CvSourceCleanup)
            .values(storage_key=storage_key, attempts=0)
            .on_conflict_do_nothing(index_elements=["storage_key"])
        )


async def clean_pending_sources(db, limit=20):
    now = datetime.now(timezone.utc)
    intents = list(
        (
            await db.scalars(
                select(CvSourceCleanup)
                .where(CvSourceCleanup.next_attempt_at <= now)
                .order_by(CvSourceCleanup.next_attempt_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for intent in intents:
        referenced = await db.scalar(
            select(CvGenerationJob.id)
            .where(CvGenerationJob.input_storage_key == intent.storage_key)
            .limit(1)
        )
        if referenced is not None:
            intent.next_attempt_at = now + timedelta(hours=24)
            continue
        try:
            await run_in_threadpool(object_storage.delete_cv, intent.storage_key)
        except Exception:
            # Keep durable retry state, without logging a private source key or
            # storage exception. Retrying an already deleted object is safe.
            intent.attempts += 1
            intent.next_attempt_at = now + timedelta(
                seconds=min(3600, 30 * 2 ** min(intent.attempts, 7))
            )
        else:
            await db.delete(intent)
    await db.commit()


def _retired_job_filter(cutoff: datetime):
    """Jobs whose private input no result can use any more.

    Kept: every attempt still queued or running, and every input a result can
    still need — the approval source review (`load_review_source`) and the
    version map (`load_upload_requirements`) re-read the frozen input of a
    READY document, including a ready first language next to a failed second
    one. Retired, `cutoff` after the attempt ended:
    - a generation that produced no usable document (job failed/interrupted,
      every linked document failed or already gone);
    - a rule preview (any finished state): its results live on the preview
      row, the input is read only while the attempt runs.
    """
    usable_document = exists().where(
        or_(
            CvGeneratedDocument.id == CvGenerationJob.generated_id,
            CvGeneratedDocument.id == CvGenerationJob.second_generated_id,
        ),
        CvGeneratedDocument.status != "failed",
    )
    running_preview = exists().where(
        ClientCvRulePreview.id == CvGenerationJob.preview_id,
        ClientCvRulePreview.status == "processing",
    )
    return and_(
        ~CvGenerationJob.input_storage_key.startswith(PURGED_KEY_PREFIX),
        func.coalesce(CvGenerationJob.finished_at, CvGenerationJob.updated_at) < cutoff,
        or_(
            and_(
                CvGenerationJob.kind.in_(("new", "upload")),
                CvGenerationJob.status.in_(("failed", "interrupted")),
                ~usable_document,
            ),
            and_(
                CvGenerationJob.kind == "preview",
                CvGenerationJob.status.in_(("complete", "failed", "interrupted")),
                ~running_preview,
            ),
        ),
    )


async def retire_unneeded_job_inputs(db, *, now=None, limit=50) -> int:
    """Hand inputs of finished, unusable attempts to the deletion ledger.

    A failed generation used to keep the candidate's complete CV, screening
    notes and Champion in object storage for good — removed only by a manual
    document delete or a candidate erasure. The sweep never touches storage:
    it re-points the job at a `purged/` marker and records the old key in
    `cv_source_cleanup` in ONE transaction, and `clean_pending_sources` (the
    loop below) deletes the object with its retry/backoff — the same durable
    path as every other source deletion. Rows locked by anyone are skipped.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max(1, int(settings.CV_JOB_INPUT_RETENTION_DAYS)))
    jobs = list(
        (
            await db.scalars(
                select(CvGenerationJob)
                .where(_retired_job_filter(cutoff))
                .order_by(CvGenerationJob.id)
                .limit(limit)
                .with_for_update(skip_locked=True, of=CvGenerationJob)
            )
        ).all()
    )
    for job in jobs:
        key = job.input_storage_key
        job.input_storage_key = f"{PURGED_KEY_PREFIX}{job.id}"
        job.prepared_source_facts = None
        await schedule_source_cleanup(db, key)
    await db.commit()
    if jobs:
        logger.info("CV input retention: %d finished attempt(s) retired", len(jobs))
    return len(jobs)


async def recovery_loop():
    last_retention = float("-inf")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await clean_pending_sources(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("CV source cleanup will retry after transaction failure")
        if (
            settings.CV_JOB_INPUT_RETENTION_ENABLED
            and time.monotonic() - last_retention >= RETENTION_INTERVAL_SECONDS
        ):
            # Stamped BEFORE the attempt: a failing sweep retries on the next
            # interval, not on every 30-second tick.
            last_retention = time.monotonic()
            try:
                async with AsyncSessionLocal() as db:
                    await retire_unneeded_job_inputs(db)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("CV input retention sweep will retry later")
        await asyncio.sleep(30)
