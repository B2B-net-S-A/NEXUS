"""Zapis licznika użycia obszarów i jego retencja.

Pętla biegnie NIEZALEŻNIE od ``ACCESS_USAGE_COUNTER_ENABLED``: wyłączenie licznika
nie może zatrzymać kasowania tego, co już zebrał. Przy wyłączonym liczniku cykl
zapisu nie dotyka bazy, bo nie ma czego zapisać.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.services.access_usage import flush_pending, prune_expired

logger = logging.getLogger(__name__)

_FLUSH_INTERVAL_SECONDS = 60
_PRUNE_INTERVAL_SECONDS = 24 * 3600


async def access_usage_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie ``main.py``."""

    next_prune_at = 0.0
    while True:
        await asyncio.sleep(_FLUSH_INTERVAL_SECONDS)
        try:
            await flush_pending()
            if time.monotonic() >= next_prune_at:
                pruned = await prune_expired()
                next_prune_at = time.monotonic() + _PRUNE_INTERVAL_SECONDS
                if pruned:
                    logger.info("access_usage: skasowano %s starych wierszy", pruned)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            # Sam typ: liczby czekają w pamięci, następna próba za minutę.
            logger.warning("access_usage: cykl padł: %s", type(exc).__name__)
