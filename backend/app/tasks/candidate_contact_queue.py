"""Restart-safe processing loop for the global candidate contact queue."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)


async def run_candidate_contact_queue_once(*, now: datetime | None = None):
    """Process one bounded queue batch and commit it atomically.

    ``process_contact_cases`` owns row claiming (``FOR UPDATE SKIP LOCKED``)
    and durable event markers.  Keeping the transaction here means a worker
    crash cannot leave a half-applied turnover or cooldown transition.
    """

    if not (
        settings.CANDIDATE_CONTACT_ENABLED
        and settings.CANDIDATE_CONTACT_ASSIGNMENT_ENABLED
    ):
        return None

    from app.services.candidate_contact import process_contact_cases

    batch_size = max(1, min(int(settings.CANDIDATE_CONTACT_WORKER_BATCH_SIZE), 500))
    async with AsyncSessionLocal() as db:
        stats = await process_contact_cases(db, now=now, limit=batch_size)
        await db.commit()
        return stats


async def candidate_contact_queue_loop() -> None:
    """Continuously process due cases; both feature gates default to OFF."""

    if not (
        settings.CANDIDATE_CONTACT_ENABLED
        and settings.CANDIDATE_CONTACT_ASSIGNMENT_ENABLED
    ):
        logger.info("Candidate contact queue worker disabled")
        return

    interval = max(
        15, min(int(settings.CANDIDATE_CONTACT_WORKER_INTERVAL_SECONDS), 3600)
    )
    logger.info(
        "Candidate contact queue worker started interval=%ss batch=%s",
        interval,
        settings.CANDIDATE_CONTACT_WORKER_BATCH_SIZE,
    )
    while True:
        try:
            stats = await run_candidate_contact_queue_once()
            if stats is not None and any(vars(stats).values()):
                logger.info("Candidate contact queue processed stats=%s", vars(stats))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Candidate contact queue tick failed")
        await asyncio.sleep(interval)


__all__ = [
    "candidate_contact_queue_loop",
    "run_candidate_contact_queue_once",
]
