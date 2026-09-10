"""Retry source deletion only for committed, explicitly removed document owners."""

import asyncio
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from starlette.concurrency import run_in_threadpool
from app.core.database import AsyncSessionLocal
from app.models.cv_generation_job import CvGenerationJob
from app.models.cv_source_cleanup import CvSourceCleanup
from app.services import object_storage

logger = logging.getLogger(__name__)


async def schedule_source_cleanup(db, storage_key: str):
    """Caller commits this intent with the deletion. Never touch storage here."""
    if storage_key:
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


async def recovery_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await clean_pending_sources(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("CV source cleanup will retry after transaction failure")
        await asyncio.sleep(30)
