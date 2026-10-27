"""Liczby osób wierszy wymagań otwartych rekrutacji — w tle, do pamięci procesu.

Powód „rare_word” w „Wymaganiach do poprawy” potrzebuje liczby osób każdego
wiersza „musi mieć”. Pomiar 27.10.2026 na kopii z 22.10: 673 wiersze w 202
otwartych rekrutacjach liczą się razem ok. 7 min (popularne słowo do 2,7 s),
więc pulpit nie może ich liczyć w żądaniu. Pętla dolicza brakujące i bliskie
wygaśnięcia wpisy co godzinę, jeden po drugim; pulpit liczy sam tylko nowe
wiersze, w limicie ``requirement_row_counts.BUDGET_SECONDS``.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

# Start po rozgrzaniu procesu — nie konkuruje z pierwszymi żądaniami po deployu.
_START_DELAY_SECONDS = 120
_EVERY_SECONDS = 3600
# Jeden obrót: wszystkie otwarte rekrutacje, ale nie dłużej niż godzinę.
_PASS_BUDGET_SECONDS = 3600.0


async def requirement_row_counts_loop() -> None:
    from app.services import requirement_cleanup

    await asyncio.sleep(_START_DELAY_SECONDS)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                counted = await requirement_cleanup.warm_counts(
                    db, budget=_PASS_BUDGET_SECONDS
                )
                await db.rollback()
            if counted:
                logger.info("requirement row counts: %d wierszy policzonych", counted)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning(
                "requirement row counts: obrót nieudany (%s)", type(exc).__name__
            )
        await asyncio.sleep(_EVERY_SECONDS)
