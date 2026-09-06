"""Cykliczne domykanie kont po odejściach z COMPASSA (Etap 5).

Pętla budzi się co ``COMPASS_LIFECYCLE_SYNC_INTERVAL_SECONDS`` i deaktywuje
w NEXUSIE konta osób, które w COMPASSIE mają ``employment_status = 'exited'``.

Kończy się PRZED pierwszym odczekaniem, gdy wyłączona — wzorzec z D5, żeby nie
powtórzyć CloudTalka, gdzie proces wstawał co 60 s wyłącznie po to, by
natychmiast sprawdzić tę samą flagę i zasnąć.
"""

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.compass_lifecycle import sync_user_lifecycle

logger = logging.getLogger(__name__)

# Dolny próg odstępu. Bez niego literówka w env (np. 60) zamieniłaby COMPASSA
# w cel odpytywany co minutę — lustro `_MIN_INTERVAL_SECONDS` z D5.
_MIN_INTERVAL_SECONDS = 900


async def compass_lifecycle_sync_loop() -> None:
    if not settings.COMPASS_LIFECYCLE_ENABLED:
        logger.info("compass_lifecycle_sync disabled — pętla nie startuje")
        return
    if not (settings.COMPASS_LIFECYCLE_URL and settings.COMPASS_LIFECYCLE_SECRET):
        logger.warning("compass_lifecycle_sync misconfigured — brak URL albo sekretu")
        return

    interval = max(
        _MIN_INTERVAL_SECONDS, int(settings.COMPASS_LIFECYCLE_SYNC_INTERVAL_SECONDS)
    )

    while True:
        try:
            async with AsyncSessionLocal() as db:
                result = await sync_user_lifecycle(db)
            logger.info(
                "compass_lifecycle_sync done received=%s matched=%s deactivated=%s "
                "already_inactive=%s unmatched_compass=%s nexus_without_compass=%s "
                "error=%s",
                result.people_received,
                result.matched_users,
                len(result.deactivated),
                result.already_inactive,
                len(result.unmatched_compass_emails),
                len(result.nexus_users_without_compass),
                result.error,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla ma przeżyć awarię COMPASSA
            logger.exception("compass_lifecycle_sync failed: %s", exc)

        await asyncio.sleep(interval)


__all__ = ["compass_lifecycle_sync_loop"]
