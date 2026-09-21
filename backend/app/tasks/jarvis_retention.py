"""Retencja rozmów Jarvisa i wygaszanie nierozstrzygniętych propozycji.

Rozmowy niosą dane osobowe (nazwiska, fragmenty CV z wyników narzędzi), więc
żyją najwyżej ``JARVIS_RETENTION_DAYS`` od ostatniej aktywności. Pętla biegnie
NIEZALEŻNIE od ``JARVIS_ENABLED``: wyłączenie asystenta nie może zatrzymać
kasowania tego, co już zapisał.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.jarvis import store

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 120
_INTERVAL_SECONDS = 3600


async def prune_once() -> dict[str, int]:
    expired = await store.expire_stale_actions(settings.JARVIS_ACTION_TTL_MINUTES)
    purged = await store.purge_old_conversations(
        max(1, int(settings.JARVIS_RETENTION_DAYS))
    )
    return {"actions_expired": expired, "conversations_purged": purged}


async def jarvis_retention_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie ``main.py``."""
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        try:
            stats = await prune_once()
            if any(stats.values()):
                logger.info("jarvis_retention: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("jarvis_retention: cykl padł")
        await asyncio.sleep(_INTERVAL_SECONDS)
