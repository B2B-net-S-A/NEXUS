"""Uzupełnienie korpusu słów kluczowych dla kandydatów sprzed migracji 0350 i 0385.

Migracje dodają kolumny i triggery, ale nie liczą wierszy, które już są —
backfill 62 tys. CV w starcie kontenera trzymał publiczny adres na 502 przez
ponad 6 minut (0143, 23.06.2026). Ta pętla robi to po starcie, paczkami po
``_BATCH`` wierszy z krótką przerwą, i kończy się, gdy nie zostaje żaden wiersz
bez korpusu. Nowe i zmieniane wiersze liczą już triggery.

Trzy fazy, każda z własną flagą gotowości:

1. ``keyword_doc``/``keyword_fts`` (0350) → ``keyword_corpus.ready()``;
2. ``candidates.keyword_fold_fts`` (0385) → ``fold_ready()``;
3. ``notes.content_fold_fts`` (0385) → ``notes_ready()``. Ta sama aktualizacja
   rozpakowuje notatki zapisane przez import z Traffita jako JSON; wynik
   (ile było i ile zostało) trafia do paragonu w ``app_settings``.

Do końca fazy zapytania korzystają ze starej ścieżki — wyniki są pełne przez
cały czas.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services import keyword_corpus

logger = logging.getLogger(__name__)

_BATCH = 500
_NOTES_BATCH = 2000
_PAUSE_SECONDS = 0.5
# Błąd bazy (deploy, restart postgresa) — spróbuj ponownie, nie kończ pętli:
# zakończona pętla zostawiłaby gałąź zapasową w zapytaniach do restartu.
_RETRY_SECONDS = 60


async def _pending(sql: str = keyword_corpus.PENDING_EXISTS_SQL) -> bool:
    async with AsyncSessionLocal() as db:
        return bool((await db.execute(text(sql))).scalar())


class TriggerMissing(RuntimeError):
    """Paczka przeszła, a korpus dalej pusty — triggera nie ma."""


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


async def _fill_keyset_batch(sql: str, after: int, limit: int, trigger: str) -> int:
    """Jedna paczka po kluczu ``id > after``; zwraca największe id albo 0."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(text(sql), {"after": after, "limit": limit})
        rows = result.all()
        if rows and not any(bool(row[1]) for row in rows):
            await db.rollback()
            raise TriggerMissing(f"trigger {trigger} missing")
        await db.commit()
        return max((int(row[0]) for row in rows), default=0)


async def _count(sql: str) -> int:
    async with AsyncSessionLocal() as db:
        return int((await db.execute(text(sql))).scalar() or 0)


async def _write_notes_receipt(
    wrapped_before: int, wrapped_after: int, rows: int
) -> None:
    receipt = {
        "wrapped_before": wrapped_before,
        "unwrapped": max(wrapped_before - wrapped_after, 0),
        "wrapped_left": wrapped_after,
        "rows_indexed": rows,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {
                "key": keyword_corpus.NOTES_UNWRAP_RECEIPT_KEY,
                "value": json.dumps(receipt),
            },
        )
        await db.commit()
    logger.info("notes content unwrap receipt: %s", receipt)


async def _legacy_phase() -> None:
    total = 0
    while await _pending():
        total += await _fill_batch()
        if total and total % (_BATCH * 20) < _BATCH:
            logger.info("keyword corpus backfill: %d rows so far", total)
        await asyncio.sleep(_PAUSE_SECONDS)
    keyword_corpus.mark_ready(True)
    if total:
        logger.info("keyword corpus backfill done: %d rows", total)


async def _fold_phase() -> None:
    total = 0
    while await _pending(keyword_corpus.FOLD_PENDING_EXISTS_SQL):
        after = 0
        while True:
            last = await _fill_keyset_batch(
                keyword_corpus.FOLD_BACKFILL_BATCH_SQL,
                after,
                _BATCH,
                keyword_corpus.TRIGGER_NAME,
            )
            if not last:
                break
            total += _BATCH
            after = last
            await asyncio.sleep(_PAUSE_SECONDS)
        # Nowe wiersze liczy trigger; kolejne okrążenie (po ponownym sprawdzeniu)
        # łapie tylko to, co ktoś wyzerował w trakcie przejścia.
    keyword_corpus.mark_fold_ready(True)
    if total:
        logger.info("keyword fold corpus backfill done: ~%d rows", total)


async def _notes_phase() -> None:
    if not await _pending(keyword_corpus.NOTES_PENDING_EXISTS_SQL):
        keyword_corpus.mark_notes_ready(True)
        return
    wrapped_before = await _count(keyword_corpus.NOTES_WRAPPED_COUNT_SQL)
    total = 0
    while await _pending(keyword_corpus.NOTES_PENDING_EXISTS_SQL):
        after = 0
        while True:
            last = await _fill_keyset_batch(
                keyword_corpus.NOTES_BACKFILL_BATCH_SQL,
                after,
                _NOTES_BATCH,
                keyword_corpus.NOTE_TRIGGER_NAME,
            )
            if not last:
                break
            total += _NOTES_BATCH
            after = last
            await asyncio.sleep(_PAUSE_SECONDS)
    wrapped_after = await _count(keyword_corpus.NOTES_WRAPPED_COUNT_SQL)
    await _write_notes_receipt(wrapped_before, wrapped_after, total)
    keyword_corpus.mark_notes_ready(True)


async def keyword_corpus_backfill_loop() -> None:
    phases = (_legacy_phase, _fold_phase, _notes_phase)
    index = 0
    while index < len(phases):
        try:
            await phases[index]()
            index += 1
        except asyncio.CancelledError:
            raise
        except TriggerMissing as exc:
            # Zapytania dalej działają (stara ścieżka); trigger dołoży następny
            # start przez siatkę DDL w entrypoincie.
            logger.error("keyword corpus backfill stopped: %s", exc)
            return
        except Exception as exc:  # noqa: BLE001
            logger.warning("keyword corpus backfill failed, retrying: %r", exc)
            await asyncio.sleep(_RETRY_SECONDS)
