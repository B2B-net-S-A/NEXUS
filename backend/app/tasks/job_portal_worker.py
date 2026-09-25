"""Worker kolejki publikacji na portalach (0360, 0381).

Kończy się PRZED pętlą, gdy żaden portal nie jest włączony
(``PORTAL_PRACUJ_ENABLED``, ``PORTAL_JJIT_ENABLED``,
``PORTAL_ROCKETJOBS_ENABLED``) i nie ma konfiguracji konta JustJoin.IT/
RocketJobs — wtedy się nie rejestruje w ``loop_heartbeat`` i nie może być
„stalled”. Włączony: tick na początku każdej iteracji; zamknięcia ogłoszeń
rekrutacji nieopublikowanych, potem dzierżawa paczki i wiersz po wierszu
(osobna transakcja na wynik), potem synchronizacja stanu żywych ogłoszeń.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import job_portals, loop_heartbeat

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS = 15


async def job_portal_worker_loop() -> None:
    from app.services.job_portals import jjit_connection

    # Konto JustJoin.IT/RocketJobs skonfigurowane = worker działa także przy
    # wyłączonych flagach: flaga blokuje nowe publikacje, nie zamykanie już
    # opłaconych ogłoszeń (zamknięcie rekrutacji, „Wycofaj”).
    if not (job_portals.any_enabled() or jjit_connection.oauth_configured()):
        logger.info("job_portal_worker disabled — żaden portal nie jest włączony")
        return

    from app.services.job_portals.service import (
        close_postings_of_closed_jobs,
        process_batch,
        sync_remote_states,
    )

    interval = max(
        _MIN_INTERVAL_SECONDS, int(settings.JOB_PORTAL_WORKER_INTERVAL_SECONDS)
    )
    # Paczka = do 5 wierszy × kilka wywołań portalu (limit czasu 30 s każde).
    beat = loop_heartbeat.register(
        "job_portal_worker", max_silence_seconds=interval + 3600
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                await close_postings_of_closed_jobs(db)
                await db.commit()
                processed = await process_batch(db, limit=5)
            if processed:
                logger.info("job_portal_worker processed=%s", processed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — kolejka ponowi w następnym biegu
            logger.error("job_portal_worker batch failed: %s", type(exc).__name__)
        try:
            await sync_remote_states()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — stan sprawdzimy w następnym biegu
            logger.warning(
                "job_portal_worker status sync failed: %s", type(exc).__name__
            )
        await asyncio.sleep(interval)
