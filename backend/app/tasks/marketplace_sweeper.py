"""Background loop — Targ kandydatów safety-net sweeper.

Co `settings.MARKETPLACE_SWEEP_INTERVAL_SECONDS` sekund:
1. auto_sync_marketplace_membership — dodaje kandydatów z availability=
   actively_looking/open_to_offers, usuwa wygasłe ręczne wrzuty oraz
   auto-wpisy, których status wyszedł z eligible.
2. rescan_recent_jobs — rescan jobów zmienionych w ostatnich 2h.
   Dedup przez uq_marketplace_alert_pair gwarantuje że żadne duplikaty
   nie powstaną nawet jeśli BackgroundTasks z create_job już je przetworzył.

Wzorzec: app/tasks/kpi_coach_nudger.py
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.marketplace_service import (
    auto_sync_marketplace_membership,
    rescan_recent_jobs,
)

logger = logging.getLogger(__name__)


async def marketplace_sweeper_loop() -> None:
    """Entry-point zarejestrowany w `app/main.py` lifespan."""
    if not settings.MARKETPLACE_ENABLED:
        logger.info("marketplace_sweeper_loop disabled via MARKETPLACE_ENABLED=false")
        return

    interval = max(300, settings.MARKETPLACE_SWEEP_INTERVAL_SECONDS)

    # Startup grace — niech DB/Qdrant/loader dojdą do formy.
    await asyncio.sleep(90)

    logger.info("marketplace_sweeper_loop started (interval=%ds)", interval)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                counters = await auto_sync_marketplace_membership(db)
                await db.commit()

                rescanned = await rescan_recent_jobs(db, lookback=timedelta(hours=2))
                await db.commit()

                if (
                    counters.added
                    or counters.removed_status_change
                    or counters.removed_expired
                    or rescanned
                ):
                    logger.info(
                        "marketplace sweep: added=%d removed_status=%d "
                        "removed_expired=%d rescanned_jobs=%d",
                        counters.added,
                        counters.removed_status_change,
                        counters.removed_expired,
                        rescanned,
                    )
                else:
                    logger.debug("marketplace sweep: no changes")
        except asyncio.CancelledError:
            logger.info("marketplace_sweeper_loop cancelled")
            raise
        except Exception:
            logger.exception("marketplace_sweeper_loop: iteration failed")
        await asyncio.sleep(interval)
