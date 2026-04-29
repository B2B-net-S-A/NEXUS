"""Background loop that refreshes stale LinkedIn profiles via Proxycurl.

Same shape as `app/tasks/microsoft365_sync.py`:
- Grace period at startup so the rest of the app finishes bootstrap.
- Infinite `while True` opening fresh DB sessions per iteration.
- Per-candidate failures are logged + recorded on the row; the loop never dies.
- CancelledError propagates so lifespan shutdown works cleanly.

Configuration (`app.core.config.settings`):
- `PROXYCURL_ENABLED` — kill-switch
- `PROXYCURL_API_KEY` — empty disables the loop
- `PROXYCURL_SYNC_INTERVAL_SECONDS` — tick cadence (min 60s)
- `PROXYCURL_CANDIDATE_STALE_DAYS` — candidate eligible after this cutoff
- `PROXYCURL_BATCH_SIZE` — max candidates per tick
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.services.proxycurl import ProxycurlClient, sync_candidate_linkedin

logger = logging.getLogger(__name__)


async def linkedin_sync_loop() -> None:
    """Long-running task — refreshes LinkedIn profiles on a schedule."""
    if not settings.PROXYCURL_ENABLED:
        logger.info("linkedin_sync_loop disabled by PROXYCURL_ENABLED=false")
        return
    if not settings.PROXYCURL_API_KEY:
        logger.info("linkedin_sync_loop disabled: PROXYCURL_API_KEY empty")
        return

    interval = max(60, settings.PROXYCURL_SYNC_INTERVAL_SECONDS)
    logger.info("linkedin_sync_loop started: interval=%ds", interval)
    # Let the rest of the app finish bootstrapping before hitting Proxycurl.
    await asyncio.sleep(45)

    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("linkedin_sync_loop iteration failed")
        await asyncio.sleep(interval)


async def _tick() -> None:
    """One pass: pick up to BATCH_SIZE stale active candidates and sync each."""
    cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.PROXYCURL_CANDIDATE_STALE_DAYS
    )
    async with AsyncSessionLocal() as db:
        stmt = (
            select(Candidate.id)
            .where(Candidate.status == CandidateStatus.active)
            .where(Candidate.linkedin.isnot(None))
            .where(
                or_(
                    Candidate.linkedin_synced_at.is_(None),
                    Candidate.linkedin_synced_at < cutoff,
                )
            )
            .order_by(Candidate.linkedin_synced_at.asc().nulls_first())
            .limit(settings.PROXYCURL_BATCH_SIZE)
        )
        candidate_ids = list((await db.execute(stmt)).scalars().all())

    if not candidate_ids:
        return

    logger.info("linkedin_sync tick — %d candidate(s) due", len(candidate_ids))

    # One shared client reused across the batch — reuses HTTP connections,
    # honors the class-level Semaphore so concurrent batches across processes
    # still cap at 4 in-flight calls.
    async with ProxycurlClient() as client:
        for cid in candidate_ids:
            try:
                async with AsyncSessionLocal() as db:
                    cand = await db.get(Candidate, cid)
                    if cand is None or cand.status != CandidateStatus.active:
                        continue
                    await sync_candidate_linkedin(db, cand, client=client)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("sync_candidate_linkedin failed for id=%s", cid)
            # Stagger so Proxycurl rate limits don't kick in.
            await asyncio.sleep(2)
