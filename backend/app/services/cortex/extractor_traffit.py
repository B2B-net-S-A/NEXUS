"""Cortex — ekstraktor faktów z Traffitowego pola ``traffit_technologie``.

Bez LLM: pole to przecinkowana lista technologii wpisana ręcznie w Traffit
("Tenable, Nessus, SIEM, WiZ, ..."), obecna u ~55% bazy (discovery §2b).
Split → normalizacja przez taksonomię → upsert faktów ``source="traffit"``
(confidence=0.8, level/years=NULL — źródło ich nie niesie, observed_at=NULL —
Traffit nie daje daty sygnału; evidence = surowy token przed normalizacją).

Odporność (audyt P0/P1):
- **reconcile** per kandydat — skill usunięty ze źródła znika z fact store;
- **savepoint** per kandydat — zatruta transakcja jednego nie ubija całego runu;
- **trwały run** (``cortex_extraction_runs``) + heartbeat — restart-safe status;
- **delta** (``since``) — faza w daily Traffit sync przetwarza tylko zmienionych.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.cortex import runs
from app.services.cortex.fact_store import (
    RawSkillToken,
    load_taxonomy,
    normalize_and_upsert,
)

logger = logging.getLogger(__name__)

SOURCE = "traffit"
TRAFFIT_CONFIDENCE = 0.8

# Parytet z scoring_service._split_skill_tokens (przecinek/średnik/newline,
# NIE "/" — "CI/CD" i "TCP/IP" przeżywają) — ale bez lowercase, bo surowy
# token w oryginalnej pisowni idzie do ``evidence``.
_RAW_SPLIT_RE = re.compile(r"[,;\n]+")

_COMMIT_EVERY = 100
_LOG_EVERY = 500

# Ile ID padłych wierszy zmieści się w statystykach runu. Lustro
# ``PhaseProgress._MAX_ERROR_REFS`` (``app/services/traffit/importer.py``) —
# świadomie skopiowana liczba, nie import: ekstraktor Cortexa nie ma dziś
# żadnej krawędzi do importera Traffita i nie warto jej zakładać dla stałej.
# Powyżej tego progu to nie jest zatruty wiersz, tylko awaria systemowa, więc
# nadmiar ma zostać NIEprzypisany (i dalej mrozić watermark). Cap chroni też
# JSONB ``cortex_extraction_runs.stats`` — pełny reconcile po awarii taksonomii
# wpisałby tam 49k identyfikatorów.
_MAX_ERROR_IDS = 500


def split_traffit_technologie(value: str) -> list[str]:
    """Podziel surowe pole na tokeny (oryginalna pisownia zachowana)."""
    if not value:
        return []
    return [t.strip() for t in _RAW_SPLIT_RE.split(value) if t.strip()]


def _content_hash(raw: str) -> str:
    """Fingerprint surowego źródła (pod przyszły skip-unchanged / provenance)."""
    return hashlib.sha256((raw or "").encode("utf-8")).hexdigest()


async def run_traffit_backfill(
    db: AsyncSession,
    *,
    limit: Optional[int] = None,
    since: Optional[datetime] = None,
    reconcile: bool = True,
    run_id: Optional[int] = None,
    progress: Optional[dict] = None,
) -> dict:
    """Przetwórz kandydatów z niepustym ``traffit_technologie``. Zwraca staty.

    ``since`` → delta (tylko ``updated_at >= since``). ``run_id`` → heartbeat do
    ``cortex_extraction_runs``. Bez ``run_id`` działa jako czysty backfill.
    """
    taxonomy = await load_taxonomy(db)

    sql = (
        "SELECT id, cv_extracted_data->>'traffit_technologie' AS tech "
        "FROM candidates "
        "WHERE COALESCE(cv_extracted_data->>'traffit_technologie', '') <> '' "
    )
    params: dict = {}
    if since is not None:
        sql += "AND updated_at >= :since "
        params["since"] = since
    sql += "ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = (await db.execute(text(sql), params)).all()

    stats = {
        "total": len(rows),
        "processed": 0,
        "facts_upserted": 0,
        "unmatched_tokens": 0,
        "errors": 0,
        # ID wierszy, które padły — bez nich faza syncu ma tylko anonimowe
        # "errors: 3" i każdy taki błąd jest dla kwarantanny NIEprzypisany,
        # czyli mrozi watermark bezterminowo. Patrz `_attributed_progress`
        # w `app/tasks/traffit_sync.py`.
        "error_ids": [],
    }
    if progress is not None:
        progress.update(stats)

    for candidate_id, tech in rows:
        try:
            # Savepoint: błąd jednego kandydata cofa TYLKO jego zapisy, nie
            # zatruwa transakcji dla reszty batcha.
            async with db.begin_nested():
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
                    reconcile=reconcile,
                    run_id=run_id,
                    extractor_version=runs.EXTRACTOR_VERSION,
                    content_hash=_content_hash(tech or ""),
                )
            stats["facts_upserted"] += fact_stats.matched
            stats["unmatched_tokens"] += fact_stats.unmatched
        except Exception:  # noqa: BLE001 — pojedynczy kandydat nie ubija runu
            stats["errors"] += 1
            # Zatrzymaj ID: faza syncu robi z tego błąd PRZYPISANY do wiersza,
            # więc kwarantanna może zaparkować trwale zepsutego kandydata
            # zamiast mrozić watermark wszystkim pozostałym.
            if len(stats["error_ids"]) < _MAX_ERROR_IDS:
                stats["error_ids"].append(candidate_id)
            logger.exception("cortex traffit backfill failed for id=%s", candidate_id)

        stats["processed"] += 1

        if stats["processed"] % _COMMIT_EVERY == 0:
            await db.commit()
            if run_id is not None:
                await runs.heartbeat_run(
                    db, run_id, cursor_candidate_id=candidate_id, stats=dict(stats)
                )
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

    await db.commit()
    if progress is not None:
        progress.update(stats)
    logger.info("cortex traffit backfill done: %s", stats)
    return stats


async def execute_run(
    db: AsyncSession,
    run_id: int,
    *,
    since: Optional[datetime] = None,
    limit: Optional[int] = None,
    progress: Optional[dict] = None,
) -> dict:
    """Wykonaj backfill dla istniejącego wiersza runu i sfinalizuj jego status.

    Slot single-flight jest już zarezerwowany przez ``runs.create_run`` (partial
    unique ``status='running'``), więc tu tylko liczymy fakty i zamykamy run.
    """
    try:
        stats = await run_traffit_backfill(
            db,
            since=since,
            limit=limit,
            reconcile=True,
            run_id=run_id,
            progress=progress,
        )
        status = "errors" if stats.get("errors") else "ok"
        await runs.finish_run(db, run_id, status=status, stats=stats)
        return stats
    except Exception as exc:  # noqa: BLE001 — zapisz porażkę na wierszu runu
        logger.exception("cortex extraction run failed (run_id=%s)", run_id)
        await db.rollback()
        await runs.finish_run(db, run_id, status="failed", last_error=str(exc))
        raise


async def run_managed_extraction(
    db: AsyncSession,
    *,
    run_type: str,
    triggered_by: Optional[str] = None,
    since: Optional[datetime] = None,
    limit: Optional[int] = None,
    progress: Optional[dict] = None,
) -> dict:
    """Zarezerwuj slot (single-flight) i wykonaj run. No-op gdy inny run trwa."""
    run_id = await runs.create_run(
        db, run_type=run_type, triggered_by=triggered_by, source=SOURCE
    )
    if run_id is None:
        logger.info("cortex extraction skipped — another run active (%s)", run_type)
        return {"skipped": "already_running", "run_type": run_type}
    return await execute_run(db, run_id, since=since, limit=limit, progress=progress)


async def import_cortex_facts(
    db: AsyncSession, *, since: Optional[datetime] = None
) -> dict:
    """Wejście dla daily Traffit sync — delta (``since``) lub full (``since=None``)."""
    return await run_managed_extraction(
        db,
        run_type="daily" if since is not None else "full",
        triggered_by="traffit_sync",
        since=since,
    )
