"""Bounded durable search drain; empty queue does no provider work."""

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import or_, select

from app.core.database import AsyncSessionLocal
from app.models.candidate_search_run import CandidateSearchRun
from app.services.candidate_search_worker import execute_run

logger = logging.getLogger(__name__)


async def candidate_search_loop():
    while True:
        try:
            async with AsyncSessionLocal() as db:
                run_id = await db.scalar(
                    select(CandidateSearchRun.id)
                    .where(
                        CandidateSearchRun.state.in_(["queued", "running"]),
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
