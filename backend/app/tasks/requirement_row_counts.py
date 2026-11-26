"""Liczby osób wierszy wymagań otwartych rekrutacji — w tle, do pamięci procesu.

Powód „rare_word” w „Wymaganiach do poprawy” potrzebuje liczby osób każdego
wiersza „musi mieć”. Pomiar 27.10.2026 na kopii z 22.10: 673 wiersze w 202
otwartych rekrutacjach liczą się razem ok. 7 min (popularne słowo do 2,7 s),
więc pulpit nie może ich liczyć w żądaniu. Pętla dolicza brakujące i bliskie
wygaśnięcia wpisy co godzinę, jeden po drugim; pulpit liczy sam tylko nowe
wiersze, w limicie ``requirement_row_counts.BUDGET_SECONDS``.

Pamięć procesu ma kopię wspólną w ``app_settings`` (26.11.2026): nowy proces
web wczytuje ją od razu, a obrót zapisuje policzone co ``_SAVE_EVERY_SECONDS``.
"""

from __future__ import annotations

import asyncio
import logging
import time

from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

# Start po rozgrzaniu procesu — nie konkuruje z pierwszymi żądaniami po deployu.
_START_DELAY_SECONDS = 120
_EVERY_SECONDS = 3600
# Jeden obrót: wszystkie otwarte rekrutacje, ale nie dłużej niż godzinę.
_PASS_BUDGET_SECONDS = 3600.0


# Zapis do kopii wspólnej co tyle sekund liczenia — padnięcie procesu
# w połowie obrotu nie traci policzonego (26.11.2026).
_SAVE_EVERY_SECONDS = 120.0


async def _load_shared() -> int:
    from app.services import requirement_row_counts as counts

    try:
        async with AsyncSessionLocal() as db:
            added = await counts.load_shared(db)
            await db.rollback()
        return added
    except Exception as exc:  # noqa: BLE001 — bez kopii pętla liczy sama
        logger.warning(
            "requirement row counts: kopia wspólna nieczytelna (%s)", type(exc).__name__
        )
        return 0


async def _save_shared() -> None:
    from app.services import requirement_row_counts as counts

    try:
        async with AsyncSessionLocal() as db:
            await counts.save_shared(db)
            await db.commit()
    except Exception as exc:  # noqa: BLE001 — liczby zostają w pamięci procesu
        logger.warning(
            "requirement row counts: zapis kopii wspólnej nieudany (%s)",
            type(exc).__name__,
        )


async def warm_pass(budget: float) -> int:
    """Jeden obrót: kopia wspólna → brakujące i bliskie wygaśnięcia wiersze
    (kawałkami po ``_SAVE_EVERY_SECONDS``, każdy kawałek zapisany) → koniec."""
    from app.services import requirement_cleanup

    await _load_shared()
    deadline = time.monotonic() + budget
    total = 0
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return total
        async with AsyncSessionLocal() as db:
            counted = await requirement_cleanup.warm_counts(
                db, budget=min(_SAVE_EVERY_SECONDS, left)
            )
            await db.rollback()
        if not counted:
            return total
        total += counted
        await _save_shared()


async def requirement_row_counts_loop() -> None:
    from app.services import requirement_sent_gaps

    # Kopia wspólna od razu: pulpit nowego procesu nie liczy wierszy, które
    # policzył już inny proces (zapytanie to jeden odczyt, nie konkuruje).
    await _load_shared()
    await asyncio.sleep(_START_DELAY_SECONDS)
    # Tick na początku obrotu; obrót trwa najwyżej godzinę, potem godzina przerwy.
    beat = loop_heartbeat.register(
        "requirement_row_counts",
        max_silence_seconds=int(_EVERY_SECONDS + _PASS_BUDGET_SECONDS) + 3600,
    )
    while True:
        beat.tick()
        try:
            counted = await warm_pass(_PASS_BUDGET_SECONDS)
            if counted:
                logger.info("requirement row counts: %d wierszy policzonych", counted)
            # Wiersze bez nikogo z wysłanych czytają CV, więc we własnej sesji.
            async with AsyncSessionLocal() as db:
                await requirement_sent_gaps.warm(db, budget=_PASS_BUDGET_SECONDS)
                await db.rollback()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla tła nie może paść
            logger.warning(
                "requirement row counts: obrót nieudany (%s)", type(exc).__name__
            )
        await asyncio.sleep(_EVERY_SECONDS)
