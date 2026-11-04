"""Nocne przygotowanie treści ogłoszeń dla otwartych rekrutacji (21.10.2026).

Między 0:00 a 6:00 czasu firmy (Europe/Warsaw) bierze otwarte rekrutacje bez
ogłoszenia, od najnowszej, i przygotowuje dla nich treść
(`services/job_ad/prepare.py`) — jedna rekrutacja na raz, każda we własnej
transakcji. Rano treść czeka w kolejce „Strona kariery do uzupełnienia”;
publikuje zawsze człowiek.

Model odpowiada do minuty, więc ok. 200 zaległych rekrutacji mieści się
w jednej nocy. Poza oknem pętla tylko śpi — w dzień model obsługuje ludzi.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.services.job_ad import prepare

logger = logging.getLogger(__name__)

_START_DELAY_SECONDS = 900
_CHECK_SECONDS = 1800
_NIGHT_HOURS = range(0, 6)
# Rekrutacje na jedno przebudzenie; następne za `_CHECK_SECONDS`.
_BATCH = 40


def in_night_window() -> bool:
    return local_now().hour in _NIGHT_HOURS


async def run_batch(limit: int = _BATCH) -> int:
    """Przygotowuje najwyżej ``limit`` ogłoszeń; zwraca liczbę zapisanych."""
    async with AsyncSessionLocal() as db:
        job_ids = await prepare.missing_job_ids(db, limit=limit)
    written = 0
    for job_id in job_ids:
        if not in_night_window():
            break
        async with AsyncSessionLocal() as db:
            try:
                if await prepare.prepare_one(db, job_id):
                    written += 1
                await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — jedna rekrutacja nie zatrzymuje reszty
                await db.rollback()
                logger.warning(
                    "job ad prepare: job=%s failed (%s)", job_id, type(exc).__name__
                )
    if job_ids:
        logger.info("job ad prepare: %s/%s ads written", written, len(job_ids))
    return written


async def job_ad_prepare_loop() -> None:
    await asyncio.sleep(_START_DELAY_SECONDS)
    while True:
        try:
            if in_night_window():
                await run_batch()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — zadanie tła nie może paść
            logger.warning("job ad prepare: batch failed (%s)", type(exc).__name__)
        await asyncio.sleep(_CHECK_SECONDS)
