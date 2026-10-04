"""Pętla przeliczeń „Stawki od” (0414).

Wyzwalacze na kartach rekomendacji, etapach, stawce profilu i zgłoszeniach
dopisują kandydata do ``candidate_rate_from_queue`` (także przy surowym
SQL-u importu Traffita). Pętla opróżnia kolejkę paczkami; pierwsze
uruchomienie po migracji to ok. 15 tys. kandydatów. Zapis z ekranu przelicza
kandydata od razu w żądaniu (``candidate_rate_from.recompute_safely``).
Wyłączona flagą ``CANDIDATE_RATE_FROM_ENABLED`` kończy się przed pętlą.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import candidate_rate_from as rate_from
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 30
_PAUSE_SECONDS = 0.5
_BATCH = 500


async def _drain() -> int:
    total = 0
    while True:
        async with AsyncSessionLocal() as db:
            done = await rate_from.process_queue(db, limit=_BATCH)
            await db.commit()
        total += done
        if done < _BATCH:
            return total
        await asyncio.sleep(_PAUSE_SECONDS)


async def candidate_rate_from_loop() -> None:
    if not rate_from.enabled():
        return
    beat = loop_heartbeat.register(
        "candidate_rate_from", max_silence_seconds=_INTERVAL_SECONDS * 20
    )
    while True:
        beat.tick()
        try:
            processed = await _drain()
            if processed:
                logger.info("candidate rate_from: %d candidates recomputed", processed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning("candidate rate_from: tick failed (%s)", type(exc).__name__)
        await asyncio.sleep(_INTERVAL_SECONDS)
