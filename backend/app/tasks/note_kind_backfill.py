"""Rodzaj notatki dla wierszy sprzed migracji 0412 — po starcie, paczkami.

Reguły są w Pythonie (``note_kinds.classify``), więc migracja dodaje tylko
kolumnę, a ta pętla przechodzi tabelę i kończy się, gdy nie zostaje żadna
notatka bez rodzaju. Do tego czasu czytelnicy traktują taki wiersz jak zwykłą
notatkę — wyniki są pełne przez cały czas. Nowe notatki dostają rodzaj przy
zapisie, a te z importu Traffita zaraz po promocji.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services.note_kind_backfill import (
    DEFAULT_BATCH,
    classify_pending,
    reclassify_dl_pair_human_notes,
    reclassify_dl_rate_lists,
)

logger = logging.getLogger(__name__)

_PAUSE_SECONDS = 0.5
# Błąd bazy (deploy, restart postgresa) — spróbuj ponownie, nie kończ pętli.
_RETRY_SECONDS = 60


async def _reclassify_once() -> None:
    """Jednorazowe przeliczenia po zmianie reguły; błąd nie zatrzymuje pętli
    (znacznik nie powstaje, więc następny start spróbuje ponownie)."""
    for name, step in (
        ("dl_rate lists", reclassify_dl_rate_lists),
        ("dl pair notes", reclassify_dl_pair_human_notes),
    ):
        try:
            async with AsyncSessionLocal() as db:
                changed = await step(db)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning(
                "note kind reclassify (%s): failed (%s)", name, type(exc).__name__
            )
            continue
        if changed:
            logger.info(
                "note kind reclassify (%s): %d notes are now dl_rate", name, changed
            )


async def note_kind_backfill_loop() -> None:
    await _reclassify_once()
    total = 0
    while True:
        try:
            async with AsyncSessionLocal() as db:
                done = await classify_pending(db, limit=DEFAULT_BATCH)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning("note kind backfill: batch failed (%s)", type(exc).__name__)
            await asyncio.sleep(_RETRY_SECONDS)
            continue
        if not done:
            break
        total += done
        await asyncio.sleep(_PAUSE_SECONDS)
    if total:
        logger.info("note kind backfill: classified %d notes", total)
