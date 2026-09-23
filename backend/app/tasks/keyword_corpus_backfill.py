"""Uzupełnienie korpusu słów kluczowych dla kandydatów sprzed migracji 0346.

Migracja dodaje kolumny i trigger, ale nie liczy wierszy, które już są — backfill
62 tys. CV w starcie kontenera trzymał publiczny adres na 502 przez ponad
6 minut (0143, 23.06.2026). Ta pętla robi to po starcie, paczkami po
``_BATCH`` wierszy z krótką przerwą, i kończy się, gdy nie zostaje żaden wiersz
bez korpusu. Nowe i zmieniane wiersze liczy już trigger.

Do końca pętli ``keyword_corpus.ready()`` zwraca ``False`` i zapytania dla
wierszy bez korpusu korzystają ze starych kolumn — wyniki są pełne przez cały
czas, a po zakończeniu gałąź zapasowa znika z zapytań.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import keyword_corpus

logger = logging.getLogger(__name__)

_BATCH = 500
_PAUSE_SECONDS = 0.5
# Błąd bazy (deploy, restart postgresa) — spróbuj ponownie, nie kończ pętli:
# zakończona pętla zostawiłaby gałąź zapasową w zapytaniach do restartu.
_RETRY_SECONDS = 60


async def _pending() -> bool:
    async with AsyncSessionLocal() as db:
        return bool(
            (await db.execute(text(keyword_corpus.PENDING_EXISTS_SQL))).scalar()
        )


class TriggerMissing(RuntimeError):
    """Paczka przeszła, a korpus dalej pusty — triggera 0346 nie ma."""


async def _fill_batch() -> int:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            text(keyword_corpus.BACKFILL_BATCH_SQL), {"limit": _BATCH}
        )
        filled = [bool(row[0]) for row in result.all()]
        if filled and not any(filled):
            await db.rollback()
            raise TriggerMissing(f"trigger {keyword_corpus.TRIGGER_NAME} missing")
        await db.commit()
        return len(filled)


async def keyword_corpus_backfill_loop() -> None:
    total = 0
    while True:
        try:
            if not await _pending():
                keyword_corpus.mark_ready(True)
                if total:
                    logger.info("keyword corpus backfill done: %d rows", total)
                return
            written = await _fill_batch()
            total += written
            if total and total % (_BATCH * 20) < _BATCH:
                logger.info("keyword corpus backfill: %d rows so far", total)
            await asyncio.sleep(_PAUSE_SECONDS)
        except asyncio.CancelledError:
            raise
        except TriggerMissing as exc:
            # Zapytania dalej działają (gałąź zapasowa po starych kolumnach);
            # trigger dołoży następny start przez siatkę DDL w entrypoincie.
            logger.error("keyword corpus backfill stopped: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("keyword corpus backfill failed, retrying: %r", exc)
            await asyncio.sleep(_RETRY_SECONDS)
