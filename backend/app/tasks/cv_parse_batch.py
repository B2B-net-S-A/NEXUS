"""Pętla odczytu CV wsadem (kontener worker), co ``CV_PARSER_BATCH_TICK_SECONDS``.

Wysyła CV z integracji (scrapery pracuj.pl/JJIT) jedną paczką do Message
Batches API, odbiera wyniki i zapisuje je ścieżką wgrania CV; CV bez wyniku po
``CV_PARSER_BATCH_FALLBACK_HOURS`` albo z błędem paczki czyta na żywo.
Kolejka: ``services/cv_parse_batch.py``. Pętla biegnie także przy
``CV_PARSER_BATCH_ENABLED=false``, żeby CV już w kolejce dostały odczyt na
żywo. Na stagingu stoi (``STAGING_BLOCKED_TASKS``): kopia produkcji z CV
scraperów to płatne odczyty drugi raz. Logi: same liczby.
→ docs/claude/generator-cv/odczyt-cv-scraperow-wsadem.md
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services import cv_parse_batch, loop_heartbeat

logger = logging.getLogger(__name__)


async def cv_parse_batch_loop() -> None:
    tick = max(60, int(settings.CV_PARSER_BATCH_TICK_SECONDS))
    # Odczyty na żywo w jednym ticku trwają do ok. 20 × 20 s.
    beat = loop_heartbeat.register("cv_parse_batch", max_silence_seconds=3 * tick + 600)
    client = None
    while True:
        beat.tick()
        try:
            if client is None:
                client = cv_parse_batch.make_client()
            stats = await cv_parse_batch.run_tick(client)
            if stats.any() or stats.errors:
                logger.info(
                    "cv_parse_batch tick submitted=%d batches=%d applied=%d "
                    "not_applied=%d fallback=%d timed_out=%d live=%d errors=%s",
                    stats.submitted,
                    stats.batches,
                    stats.applied,
                    stats.not_applied,
                    stats.fallback,
                    stats.timed_out,
                    stats.live,
                    stats.errors[:5],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("cv_parse_batch_loop iteration failed")
        await asyncio.sleep(tick)
