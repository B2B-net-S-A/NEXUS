"""Uzupełnienie korpusu słów kluczowych dla kandydatów sprzed migracji 0350 i 0385.

Migracje dodają kolumny i triggery, ale nie liczą wierszy, które już są —
backfill 62 tys. CV w starcie kontenera trzymał publiczny adres na 502 przez
ponad 6 minut (0143, 23.06.2026). Ta pętla robi to po starcie, paczkami po
``_BATCH`` wierszy z krótką przerwą, i kończy się, gdy nie zostaje żaden wiersz
bez korpusu. Nowe i zmieniane wiersze liczą już triggery.

Cztery fazy:

1. ``keyword_doc``/``keyword_fts`` (0350) → ``keyword_corpus.ready()``;
2. ``candidates.keyword_fold_fts`` (0385);
3. ``notes.content_fold_fts`` (0385). Ta sama aktualizacja rozpakowuje
   notatki zapisane przez import z Traffita jako JSON; wynik (ile było i ile
   zostało) trafia do paragonu w ``app_settings``;
4. wersja składania tekstu (``FOLD_VERSION``): inna niż zapisana = przeliczenie
   wszystkich wierszy obu kolumn. Dopiero po niej ``fold_ready()`` i
   ``notes_ready()``.

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
    # Gotowość ogłasza dopiero `_version_phase` (wersja składania tekstu).
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


# Pozycja przeliczania wersji — przeżywa ponowienie fazy (zakleszczenie z innym
# zapisem kandydatów, restart bazy) i RESTART KONTENERA: jest też zapisywana
# w ``app_settings``. Od 26.09.2026 każdy merge wdraża się od razu, a pełne
# przeliczenie trwa ~45 min — pozycja trzymana tylko w pamięci procesu zaczynała
# od zera po każdym wdrożeniu i przeliczenie v2 nie skończyło się ani razu.
_recompute_after: dict[str, int] = {}
_RECOMPUTE_POSITION_KEY = "keyword_fold_fts_recompute"


async def _load_recompute_position() -> dict[str, int]:
    """Zapisana pozycja przeliczania BIEŻĄCEJ wersji; inna wersja = od zera."""
    async with AsyncSessionLocal() as db:
        value = (
            await db.execute(
                text("SELECT value FROM app_settings WHERE key = :key"),
                {"key": _RECOMPUTE_POSITION_KEY},
            )
        ).scalar()
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    if (
        not isinstance(value, dict)
        or value.get("version") != keyword_corpus.FOLD_VERSION
    ):
        return {}
    position: dict[str, int] = {}
    for name in ("candidates", "notes"):
        try:
            after = int(value.get(name) or 0)
        except (TypeError, ValueError):
            continue
        if after > 0:
            position[name] = after
    return position


async def _save_recompute_position(name: str, after: int) -> None:
    payload = {
        "version": keyword_corpus.FOLD_VERSION,
        name: after,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    async with AsyncSessionLocal() as db:
        # Scalenie: druga kolumna zachowuje swoją pozycję. Wpis starszej wersji
        # jest nadpisywany w całości.
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) "
                "VALUES (:key, CAST(:value AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = CASE "
                "WHEN app_settings.value->>'version' = EXCLUDED.value->>'version' "
                "THEN app_settings.value || EXCLUDED.value ELSE EXCLUDED.value END"
            ),
            {"key": _RECOMPUTE_POSITION_KEY, "value": json.dumps(payload)},
        )
        await db.commit()


async def _clear_recompute_position() -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM app_settings WHERE key = :key"),
            {"key": _RECOMPUTE_POSITION_KEY},
        )
        await db.commit()


async def _stored_fold_version() -> int | None:
    async with AsyncSessionLocal() as db:
        value = (
            await db.execute(
                text("SELECT value FROM app_settings WHERE key = :key"),
                {"key": keyword_corpus.FOLD_VERSION_KEY},
            )
        ).scalar()
    # asyncpg oddaje jsonb z `text()` jako napis, ORM — jako słownik.
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, dict):
        value = value.get("version")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


async def _store_fold_version() -> None:
    payload = {
        "version": keyword_corpus.FOLD_VERSION,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "INSERT INTO app_settings (key, value) "
                "VALUES (:key, CAST(:value AS jsonb)) "
                "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"key": keyword_corpus.FOLD_VERSION_KEY, "value": json.dumps(payload)},
        )
        await db.commit()


async def _recompute(name: str, sql: str, limit: int, trigger: str) -> int:
    rows = 0
    while True:
        last = await _fill_keyset_batch(
            sql, _recompute_after.get(name, 0), limit, trigger
        )
        if not last:
            return rows
        _recompute_after[name] = last
        await _save_recompute_position(name, last)
        rows += limit
        await asyncio.sleep(_PAUSE_SECONDS)


async def _version_phase() -> None:
    """Zmieniona funkcja składania (``FOLD_VERSION``) = przelicz wszystko.

    Do końca przeliczania nowa ścieżka zapytań jest wyłączona
    (``fold_ready()``/``notes_ready()`` = False) — stare i nowe tokeny
    w jednej kolumnie dawałyby wyniki zależne od tego, kiedy wiersz przeliczono.
    """
    if await _stored_fold_version() != keyword_corpus.FOLD_VERSION:
        keyword_corpus.mark_fold_ready(False)
        keyword_corpus.mark_notes_ready(False)
        for name, after in (await _load_recompute_position()).items():
            _recompute_after.setdefault(name, after)
        if _recompute_after:
            logger.info(
                "keyword fold corpus v%d recompute resumed at %s",
                keyword_corpus.FOLD_VERSION,
                _recompute_after,
            )
        candidates = await _recompute(
            "candidates",
            keyword_corpus.FOLD_RECOMPUTE_BATCH_SQL,
            _BATCH,
            keyword_corpus.TRIGGER_NAME,
        )
        notes = await _recompute(
            "notes",
            keyword_corpus.NOTES_RECOMPUTE_BATCH_SQL,
            _NOTES_BATCH,
            keyword_corpus.NOTE_TRIGGER_NAME,
        )
        await _store_fold_version()
        await _clear_recompute_position()
        _recompute_after.clear()
        logger.info(
            "keyword fold corpus v%d recomputed: ~%d candidates, ~%d notes",
            keyword_corpus.FOLD_VERSION,
            candidates,
            notes,
        )
    keyword_corpus.mark_fold_ready(True)
    keyword_corpus.mark_notes_ready(True)


async def keyword_corpus_backfill_loop() -> None:
    phases = (_legacy_phase, _fold_phase, _notes_phase, _version_phase)
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
