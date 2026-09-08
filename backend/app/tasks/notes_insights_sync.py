"""Cykliczna ekstrakcja faktów z notatek — świeżość ``_notes_insights``.

Import 08.2026 przemielił pełny korpus jednorazowo (ad-hoc, ~14k kandydatów).
Notatki przybywają codziennie (Traffit daily sync + wpisy w aplikacji), więc
bez tej pętli ekstrakcje starzeją się bezterminowo: nowa stawka z rozmowy nie
trafia do warstwy finansowej scoringu, nowa dostępność nie zasila fallbacku.

Zasada kosztowa: **płacą wyłącznie kandydaci ze zmienionymi notatkami**.
Selekcja: kandydat ma notatkę nowszą niż znacznik jego ostatniej ekstrakcji
(albo nie ma ekstrakcji wcale), z sufitem ``NOTES_INSIGHTS_SYNC_BATCH_LIMIT``
na bieg — pierwsze włączenie zbiega w kilka dni zamiast jednym rachunkiem.
Wiersze z importu (bez ``_input_hash``) są honorowane jako świeże, dopóki nie
zmienią się ich notatki — patrz ``legacy_row_is_fresh``.

Wzorce operacyjne odziedziczone po ``traffit_sync``: persisted watermark
(wiersz ``notes_insights`` w ``traffit_sync_state``) zamiast timera w pamięci
(Coolify restartuje kontener przy każdym pushu), kill-switch w env, status
przez ten sam wiersz stanu.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.notes_insights_extractor import (
    MIN_BLOB_CHARS,
    apply_insights,
    build_notes_blob,
    extract_insights,
    legacy_row_is_fresh,
    load_note_rows,
    notes_fingerprint,
    stamp_no_content,
)

logger = logging.getLogger(__name__)

STATE_PHASE = "notes_insights"

_run_lock = asyncio.Lock()


def sync_is_running() -> bool:
    return _run_lock.locked()


async def _load_state() -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT last_synced_at, stats FROM traffit_sync_state "
                    "WHERE phase = :p"
                ),
                {"p": STATE_PHASE},
            )
        ).first()
    if row is None:
        return None
    return {"last_synced_at": row[0], "stats": row[1]}


async def save_state(stats: dict[str, Any]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                """
                INSERT INTO traffit_sync_state
                    (phase, last_synced_at, last_run_started_at,
                     last_run_finished_at, last_status, stats,
                     created_at, updated_at)
                VALUES (:p, now(), now(), now(), :status,
                        CAST(:stats AS jsonb), now(), now())
                ON CONFLICT (phase) DO UPDATE SET
                    last_synced_at = now(),
                    last_run_started_at = now(),
                    last_run_finished_at = now(),
                    last_status = EXCLUDED.last_status,
                    stats = EXCLUDED.stats,
                    updated_at = now()
                """
            ),
            {
                "p": STATE_PHASE,
                "status": stats.get("status", "ok"),
                "stats": json.dumps(stats, ensure_ascii=False),
            },
        )
        await db.commit()


def _is_due(last_synced_at: Optional[datetime], now: datetime) -> bool:
    """Raz dziennie po ``NOTES_INSIGHTS_SYNC_HOUR_UTC``; pierwszy bieg od razu."""
    if last_synced_at is None:
        return True
    last = last_synced_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if last.date() >= now.date():
        return False
    return now.hour >= int(settings.NOTES_INSIGHTS_SYNC_HOUR_UTC)


async def _select_stale_candidates(limit: int) -> list[int]:
    """Kandydaci z notatką nowszą niż ich znacznik ekstrakcji (lub bez niej).

    Porównanie znacznika liczone w Pythonie, nie castem w SQL — jeden zepsuty
    string w JSONB wywróciłby castem CAŁY sweep, a tu ma wypaść jeden wiersz.
    """
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    """
                    SELECT c.id,
                           c.cv_extracted_data->'_notes_insights'
                               ->>'_v2_extracted_at' AS stamp_v2,
                           c.cv_extracted_data->'_notes_insights'
                               ->>'_extracted_at' AS stamp_v1,
                           (c.cv_extracted_data ? '_notes_insights') AS has_ins,
                           ln.latest
                    FROM candidates c
                    JOIN (
                        SELECT candidate_id,
                               max(greatest(created_at, updated_at)) AS latest
                        FROM notes
                        WHERE candidate_id IS NOT NULL
                        GROUP BY candidate_id
                    ) ln ON ln.candidate_id = c.id
                    ORDER BY ln.latest DESC
                    """
                )
            )
        ).all()
    stale: list[int] = []
    for cid, stamp_v2, stamp_v1, has_ins, latest in rows:
        # Lekka projekcja: same znaczniki zamiast całego blobu insights —
        # `legacy_row_is_fresh` i tak czyta wyłącznie te dwa pola, a pełny
        # JSONB dla ~14k wierszy to dziesiątki MB na każdy dzienny bieg.
        insights = (
            {"_v2_extracted_at": stamp_v2, "_extracted_at": stamp_v1}
            if has_ins
            else None
        )
        if legacy_row_is_fresh(insights, latest):
            continue
        stale.append(int(cid))
        if len(stale) >= limit:
            break
    return stale


async def run_notes_insights_sync() -> dict[str, Any]:
    """Jeden bieg: selekcja przeterminowanych → ekstrakcja → zapis. Zwraca statystyki."""
    from app.services.index_outbox_service import CANDIDATE, record_bulk_reindex
    from app.services.match_score_cache import mark_stale_for_candidate

    limit = max(1, int(settings.NOTES_INSIGHTS_SYNC_BATCH_LIMIT))
    stats: dict[str, Any] = {
        "status": "ok",
        "selected": 0,
        "extracted": 0,
        "skipped_same_fingerprint": 0,
        "skipped_short": 0,
        "errors": 0,
        "changed": 0,
        "skills_added": 0,
        "rate_written": 0,
        "rate_updated": 0,
        "onsite_days_filled": 0,
        "quota_blocked": 0,
    }
    stale = await _select_stale_candidates(limit)
    stats["selected"] = len(stale)
    touched: list[int] = []

    for cid in stale:
        try:
            async with AsyncSessionLocal() as db:
                rows = await load_note_rows(db, cid)
                fingerprint = notes_fingerprint(rows)
                cand = (
                    await db.execute(select(Candidate).where(Candidate.id == cid))
                ).scalar_one_or_none()
                if cand is None:
                    continue
                # Bez idiomu `or {}` — cv_extracted_data na prodzie bywa listą
                # (guard-test test_no_caller_reintroduces_the_or_dict_idiom).
                prior = (
                    cand.cv_extracted_data.get("_notes_insights")
                    if isinstance(cand.cv_extracted_data, dict)
                    else None
                )
                if isinstance(prior, dict) and prior.get("_input_hash") == fingerprint:
                    stats["skipped_same_fingerprint"] += 1
                    continue
                blob = build_notes_blob(rows)
                if len(blob) < MIN_BLOB_CHARS:
                    # Stempel bez AI — inaczej klasa "no_content" wraca do
                    # selekcji każdego dnia i zjada cały budżet biegu
                    # (prod, pierwszy bieg: selected=300, skipped_short=299).
                    stamp_no_content(cand, fingerprint=fingerprint)
                    await db.commit()
                    stats["skipped_short"] += 1
                    continue
                try:
                    async with ai_feature(db, AIFeatureKey.notes_extraction):
                        parsed = await extract_insights(blob)
                except AIQuotaExceeded:
                    stats["quota_blocked"] += 1
                    stats["status"] = "quota_blocked"
                    break
                row_stats = apply_insights(cand, parsed, fingerprint=fingerprint)
                for key in (
                    "changed",
                    "skills_added",
                    "rate_written",
                    "rate_updated",
                    "onsite_days_filled",
                ):
                    stats[key] += row_stats.get(key, 0)
                if row_stats.get("changed"):
                    touched.append(cid)
                    await mark_stale_for_candidate(db, cid)
                await db.commit()
                stats["extracted"] += 1
        except Exception:  # noqa: BLE001 — jeden kandydat nie zabija biegu
            logger.exception("notes-insights: ekstrakcja padła dla id=%s", cid)
            stats["errors"] += 1

    if touched:
        async with AsyncSessionLocal() as db:
            await record_bulk_reindex(db, CANDIDATE, touched)
            await db.commit()
    if stats["errors"] and stats["status"] == "ok":
        stats["status"] = "partial"
    return stats


async def run_and_persist() -> dict[str, Any]:
    """Bieg pod lockiem + zapis stanu — wspólne dla pętli i admin triggera.

    Jeden lock znaczy, że `sync_is_running()` widzi oba źródła uruchomień
    i pętla dzienna nie wystartuje w trakcie biegu odpalonego ręcznie.
    """
    async with _run_lock:
        stats = await run_notes_insights_sync()
        await save_state(stats)
        return stats


async def notes_insights_sync_loop() -> None:
    """Pętla tła — rejestrowana w lifespanie ``main.py``.

    Wyłączona flaga kończy pętlę PRZED wejściem w while (lekcja z CloudTalka:
    pętla budząca się co minutę, żeby sprawdzić tę samą flagę, to hałas).
    """
    if not settings.NOTES_INSIGHTS_SYNC_ENABLED:
        logger.info("notes-insights sync wyłączony (NOTES_INSIGHTS_SYNC_ENABLED=false)")
        return
    interval = max(300, int(settings.NOTES_INSIGHTS_SYNC_CHECK_INTERVAL_SECONDS))
    logger.info("notes-insights sync aktywny (interwał kontroli %ss)", interval)
    while True:
        try:
            state = await _load_state()
            last = state["last_synced_at"] if state else None
            if _is_due(last, datetime.now(timezone.utc)) and not _run_lock.locked():
                stats = await run_and_persist()
                logger.info("notes-insights sync: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("notes-insights sync: bieg padł, ponowię po interwale")
        await asyncio.sleep(interval)
