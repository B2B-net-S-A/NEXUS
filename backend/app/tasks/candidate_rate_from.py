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
from app.core.scheduling import business_today
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
    expiry_day = None
    while True:
        beat.tick()
        try:
            # Raz dziennie okno 18 miesięcy przesuwa się — minimum, które z niego
            # wypadło, trzeba przeliczyć (wyzwalacze reagują tylko na zmiany).
            today = business_today()
            if expiry_day != today:
                async with AsyncSessionLocal() as db:
                    requeued = await rate_from.requeue_expiring(db, today=today)
                    await db.commit()
                expiry_day = today
                if requeued:
                    logger.info(
                        "candidate rate_from: %d minimums left the window", requeued
                    )
            processed = await _drain()
            if processed:
                logger.info("candidate rate_from: %d candidates recomputed", processed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning("candidate rate_from: tick failed (%s)", type(exc).__name__)
        await asyncio.sleep(_INTERVAL_SECONDS)
