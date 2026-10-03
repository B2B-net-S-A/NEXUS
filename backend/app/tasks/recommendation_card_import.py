"""Pętla importu kart rekomendacji z notatek (0413).

Wyłączona flagą ``RECOMMENDATION_CARD_IMPORT_ENABLED`` kończy się przed pętlą.
Włączona: najpierw nadrabia zaległość paczkami (pierwsze uruchomienie to ok.
16 tys. notatek), potem budzi się co kilka minut — nowe karty z nocnego
importu Traffita pojawiają się bez niczyjej pracy. Notatka zapisana
w NEXUSIE przelicza kartę od razu, w żądaniu (``api/notes.py``).
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import recommendation_card_import as card_import

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 300
_PAUSE_SECONDS = 0.5
# Karty po notatkach skasowanych surowym SQL-em: raz na godzinę wystarczy.
_ORPHAN_EVERY = 12


async def _drain() -> int:
    total = 0
    while True:
        async with AsyncSessionLocal() as db:
            done = await card_import.process_pending(db)
            await db.commit()
        total += done
        if done < card_import.DEFAULT_BATCH:
            return total
        await asyncio.sleep(_PAUSE_SECONDS)


async def recommendation_card_import_loop() -> None:
    if not card_import.enabled():
        return
    tick = 0
    while True:
        try:
            processed = await _drain()
            repaired = 0
            if tick % _ORPHAN_EVERY == 0:
                async with AsyncSessionLocal() as db:
                    repaired = await card_import.repair_orphans(db)
                    await db.commit()
            if processed or repaired:
                logger.info(
                    "recommendation cards: %d notes processed, %d cards repaired",
                    processed,
                    repaired,
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning(
                "recommendation card import: tick failed (%s)", type(exc).__name__
            )
        tick += 1
        await asyncio.sleep(_INTERVAL_SECONDS)
