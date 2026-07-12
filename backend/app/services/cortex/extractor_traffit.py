"""Cortex — ekstraktor faktów z Traffitowego pola ``traffit_technologie``.

Bez LLM: pole to przecinkowana lista technologii wpisana ręcznie w Traffit
("Tenable, Nessus, SIEM, WiZ, ..."), obecna u ~55% bazy (discovery §2b).
Split → normalizacja przez taksonomię → upsert faktów ``source="traffit"``
(confidence=0.8, level/years=NULL — źródło ich nie niesie, observed_at=NULL —
Traffit nie daje daty sygnału; evidence = surowy token przed normalizacją).

Kształt pętli lustruje ``cv_backfill.backfill_missing_names``: iteracja po id,
commit co ``_COMMIT_EVERY`` (re-run i tak jest idempotentny), ``progress``
dict aktualizowany na bieżąco dla endpointu statusu.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cortex.fact_store import (
    RawSkillToken,
    load_taxonomy,
    normalize_and_upsert,
    record_unmatched,
)

logger = logging.getLogger(__name__)

SOURCE = "traffit"
TRAFFIT_CONFIDENCE = 0.8

# Parytet z scoring_service._split_skill_tokens (przecinek/średnik/newline,
# NIE "/" — "CI/CD" i "TCP/IP" przeżywają) — ale bez lowercase, bo surowy
# token w oryginalnej pisowni idzie do ``evidence``.
_RAW_SPLIT_RE = re.compile(r"[,;\n]+")

_COMMIT_EVERY = 100
_UNMATCHED_FLUSH_EVERY = 500
_LOG_EVERY = 500


def split_traffit_technologie(value: str) -> list[str]:
    """Podziel surowe pole na tokeny (oryginalna pisownia zachowana)."""
    if not value:
        return []
    return [t.strip() for t in _RAW_SPLIT_RE.split(value) if t.strip()]


async def _flush_unmatched(db: AsyncSession, counter: dict[str, int]) -> None:
    for term, count in counter.items():
        await record_unmatched(db, term, count)
    counter.clear()


async def run_traffit_backfill(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    progress: Optional[dict] = None,
) -> dict:
    """Przetwórz kandydatów z niepustym ``traffit_technologie``. Zwraca staty."""
    taxonomy = await load_taxonomy(db)

    sql = (
        "SELECT id, cv_extracted_data->>'traffit_technologie' AS tech "
        "FROM candidates "
        "WHERE COALESCE(cv_extracted_data->>'traffit_technologie', '') <> '' "
        "ORDER BY id"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = (await db.execute(text(sql))).all()

    stats = {
        "total": len(rows),
        "processed": 0,
        "facts_upserted": 0,
        "unmatched_tokens": 0,
        "errors": 0,
    }
    if progress is not None:
        progress.update(stats)

    unmatched_counter: dict[str, int] = {}

    for candidate_id, tech in rows:
        try:
            tokens = [
                RawSkillToken(
                    name=raw, confidence=TRAFFIT_CONFIDENCE, evidence=raw[:300]
                )
                for raw in split_traffit_technologie(tech or "")
            ]
            fact_stats = await normalize_and_upsert(
                db,
                candidate_id=candidate_id,
                tokens=tokens,
                source=SOURCE,
                taxonomy=taxonomy,
                unmatched_counter=unmatched_counter,
            )
            stats["facts_upserted"] += fact_stats.matched
            stats["unmatched_tokens"] += fact_stats.unmatched
        except Exception:  # noqa: BLE001 — pojedynczy kandydat nie ubija runu
            stats["errors"] += 1
            logger.exception("cortex traffit backfill failed for id=%s", candidate_id)

        stats["processed"] += 1

        if stats["processed"] % _COMMIT_EVERY == 0:
            await db.commit()
        if len(unmatched_counter) >= _UNMATCHED_FLUSH_EVERY:
            await _flush_unmatched(db, unmatched_counter)
            await db.commit()
        if stats["processed"] % _LOG_EVERY == 0:
            logger.info(
                "cortex traffit backfill: %s/%s (facts=%s, unmatched=%s)",
                stats["processed"],
                stats["total"],
                stats["facts_upserted"],
                stats["unmatched_tokens"],
            )
        if progress is not None:
            progress.update(stats)

    await _flush_unmatched(db, unmatched_counter)
    await db.commit()
    if progress is not None:
        progress.update(stats)
    logger.info("cortex traffit backfill done: %s", stats)
    return stats
