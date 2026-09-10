"""Bounded durable search drain; empty queue does no provider work."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchRun
from app.services import candidate_search_store as store
from app.services.candidate_search_worker import execute_run

logger = logging.getLogger(__name__)

# Claims and checkpoints move `updated_at` every few minutes at most (lease
# 120-300 s), so half an hour without movement means nobody works on the run.
STALLED_AFTER = timedelta(minutes=30)


async def _reap_stalled() -> None:
    async with AsyncSessionLocal() as db:
        reaped = await store.reap_stalled_runs(db, stalled_after=STALLED_AFTER)
        await db.commit()
    if reaped:
        logger.warning("Candidate search reaped %s stalled run(s)", len(reaped))


async def candidate_search_loop():
    while True:
        try:
            # Before picking work: a stalled run must not keep its author's
            # active-search slot forever.
            await _reap_stalled()
            async with AsyncSessionLocal() as db:
                run_id = await db.scalar(
                    select(CandidateSearchRun.id)
                    .where(
                        CandidateSearchRun.state.in_(store.ACTIVE_STATES),
                        or_(
                            CandidateSearchRun.lease_expires_at.is_(None),
                            CandidateSearchRun.lease_expires_at
                            < datetime.now(timezone.utc),
                        ),
                    )
                    .order_by(CandidateSearchRun.created_at)
                    .limit(1)
                )
            if run_id:
                await execute_run(run_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Candidate search worker tick failed: %s", type(exc).__name__
            )
        await asyncio.sleep(5)
