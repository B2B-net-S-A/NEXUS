"""Retencja kolejek i dzienników automatów (audyt 22.09 r2, DATA-03/04/PROD-10).

Trzy tabele rosły bez końca:

* ``candidate_auto_match_log`` — ~238 tys. wierszy/dobę (164 MB w 5 dni,
  ~30 GB/rok). Decyzje ``added`` i ``proposed`` ZOSTAJĄ zawsze (to trwały ślad
  i dedup „nie dodawaj drugi raz”); pozostałe (poniżej progu, kara, dry-run)
  po ``AUTOMATION_LOG_RETENTION_DAYS``. Starsza decyzja odrzucająca nie blokuje
  już niczego: zmiana rekrutacji i tak ją unieważnia, a nowe CV ma nową wersję.
* ``candidate_match_outbox`` — zdarzenia zakończone (``done``/``skipped``/
  ``dead``) po ``QUEUE_OUTBOX_RETENTION_DAYS``. W toku (`pending`/`processing`/
  `failed`) nie dotykamy nigdy. Uwaga: nocny przegląd bazy czyta zdarzenia
  rekrutacji z okna ``AUTO_FULL_REVIEW_EVENT_LOOKBACK_DAYS`` (14 dni), więc
  retencja musi być dłuższa — pilnuje tego ``_outbox_days``.
* ``match_index_outbox`` — ``done`` po ``QUEUE_OUTBOX_RETENTION_DAYS``,
  ALE z zachowaniem najnowszego ``done`` z ``indexed_hash`` każdej encji: to
  on mówi reconcilerowi dryfu, co naprawdę jest w indeksie. Skasowanie go
  zamieniłoby encję w „nieznaną” i wyłączyło wykrywanie dryfu.

Kasujemy paczkami po ``BATCH_SIZE`` z commitem po każdej, najwyżej
``MAX_BATCHES`` paczek na tabelę w jednym cyklu — zaległość po wdrożeniu
schodzi w kilka cykli zamiast jednej wielominutowej transakcji.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.core.config import settings
from app.core.database import AsyncSessionLocal

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000
MAX_BATCHES = 50
_MIN_INTERVAL_SECONDS = 600
_INITIAL_DELAY_SECONDS = 180

_PRUNE_AUTO_MATCH_LOG = text(
    """
    DELETE FROM candidate_auto_match_log
     WHERE id IN (
        SELECT id FROM candidate_auto_match_log
         WHERE created_at < :cutoff
           AND decision NOT IN ('added', 'proposed')
         ORDER BY created_at
         LIMIT :batch
     )
    """
)

_PRUNE_MATCH_OUTBOX = text(
    """
    DELETE FROM candidate_match_outbox
     WHERE id IN (
        SELECT id FROM candidate_match_outbox
         WHERE status IN ('done', 'skipped', 'dead')
           AND created_at < :cutoff
         ORDER BY created_at
         LIMIT :batch
     )
    """
)

_PRUNE_INDEX_OUTBOX = text(
    """
    DELETE FROM match_index_outbox
     WHERE id IN (
        SELECT old.id FROM match_index_outbox AS old
         WHERE old.status = 'done'
           AND old.created_at < :cutoff
           AND EXISTS (
               SELECT 1 FROM match_index_outbox AS newer
                WHERE newer.entity_type = old.entity_type
                  AND newer.entity_id = old.entity_id
                  AND newer.status = 'done'
                  AND newer.indexed_hash IS NOT NULL
                  AND newer.id > old.id
           )
         ORDER BY old.created_at
         LIMIT :batch
     )
    """
)


def _outbox_days() -> int:
    """Nie krócej niż okno zdarzeń nocnego przeglądu + zapas."""
    floor = int(getattr(settings, "AUTO_FULL_REVIEW_EVENT_LOOKBACK_DAYS", 14)) + 1
    return max(floor, int(settings.QUEUE_OUTBOX_RETENTION_DAYS))


async def _prune(statement, *, cutoff: datetime) -> int:
    deleted = 0
    for _ in range(MAX_BATCHES):
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                statement, {"cutoff": cutoff, "batch": BATCH_SIZE}
            )
            await db.commit()
        rows = result.rowcount or 0
        deleted += rows
        if rows < BATCH_SIZE:
            break
    return deleted


async def prune_once(*, now: datetime | None = None) -> dict[str, int]:
    now = now or datetime.now(timezone.utc)
    log_cutoff = now - timedelta(
        days=max(1, int(settings.AUTOMATION_LOG_RETENTION_DAYS))
    )
    outbox_cutoff = now - timedelta(days=_outbox_days())
    return {
        "auto_match_log": await _prune(_PRUNE_AUTO_MATCH_LOG, cutoff=log_cutoff),
        "match_outbox": await _prune(_PRUNE_MATCH_OUTBOX, cutoff=outbox_cutoff),
        "index_outbox": await _prune(_PRUNE_INDEX_OUTBOX, cutoff=outbox_cutoff),
    }


async def queue_retention_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie ``main.py``."""
    if not settings.QUEUE_RETENTION_ENABLED:
        logger.info("queue_retention wyłączona (QUEUE_RETENTION_ENABLED=false)")
        return
    interval = max(
        _MIN_INTERVAL_SECONDS, int(settings.QUEUE_RETENTION_INTERVAL_SECONDS)
    )
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        try:
            stats = await prune_once()
            if any(stats.values()):
                logger.info("queue_retention: usunięto %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            # `exception`: trwale padająca retencja objawia się dopiero pełnym
            # dyskiem Postgresa — Sentry ma próg ERROR.
            logger.exception("queue_retention: cykl padł")
        await asyncio.sleep(interval)
