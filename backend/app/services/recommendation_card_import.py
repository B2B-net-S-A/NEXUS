"""Karty rekomendacji z notatek — wybór notatek do przeliczenia (0413).

Wybór jest STANEM, nie hakiem: notatka rodzaju „karta” / „fakty ze
screeningu” jest do przeliczenia, gdy jej odcisk (treść + rekrutacja +
nagrobek + wersja parsera) różni się od zapisanego w ``card_parsed_hash``.
Import z Traffita dopisuje ``job_id`` surowym SQL-em już po wstawieniu
notatki — odcisk łapie to sam, bez haka w imporcie.

Dwie siatki bezpieczeństwa:

* notatka, która zmieniła rekrutację albo rodzaj, zostawia stare pola
  w poprzedniej karcie — dlatego przy każdej notatce przeliczamy WSZYSTKIE
  karty jej kandydata;
* notatka skasowana surowym SQL-em nie ma już wiersza do wybrania —
  ``repair_orphans`` znajduje karty wskazujące na notatkę, której nie ma.

Stemplowanie odcisku NIE rusza ``notes.updated_at`` (odcisk nocnego odczytu
faktów stoi na tej kolumnie).

Karta, która się zmieniła, przelicza też arkusz screeningu pary z odpowiedzi
w notatce (``screening_note_sync``, decyzje 07.10.2026; wyłącznik
``SCREENING_NOTE_SYNC_ENABLED``). Zapis notatki w NEXUSIE i scalanie
kandydatów idą tą samą drogą (``refresh_candidate``).
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services import recommendation_cards as cards
from app.services import screening_note_sync
from app.services.recommendation_card_parser import PARSER_VERSION

logger = logging.getLogger(__name__)

DEFAULT_BATCH = 200

# Odcisk liczy baza — to samo wyrażenie wybiera notatki i trafia do stempla,
# więc zmiana treści między odczytem a stemplem wraca w następnym przebiegu.
_PENDING_SQL = text(
    "SELECT n.id, n.candidate_id, n.job_id, "
    "md5(coalesce(n.content, '') || '|' || coalesce(n.job_id::text, '') || '|' "
    "|| coalesce(n.source_deleted_at::text, '') || '|' || :version) AS hash "
    "FROM notes n WHERE n.kind IN ('card', 'screening_facts') "
    "AND n.card_parsed_hash IS DISTINCT FROM "
    "md5(coalesce(n.content, '') || '|' || coalesce(n.job_id::text, '') || '|' "
    "|| coalesce(n.source_deleted_at::text, '') || '|' || :version) "
    "ORDER BY n.id LIMIT :limit"
)
_STAMP_SQL = text("UPDATE notes SET card_parsed_hash = :hash WHERE id = :id")
_CANDIDATE_CARDS_SQL = text(
    "SELECT job_id FROM recommendation_cards WHERE candidate_id = :candidate_id"
)
# Karta ma pole albo odpowiedzi z notatki, która już nie istnieje, została
# przepięta, zmieniła rodzaj albo dostała nagrobek z Traffita.
_ORPHANS_SQL = text(
    "SELECT c.candidate_id, c.job_id FROM recommendation_cards c "
    "WHERE EXISTS ("
    "SELECT 1 FROM ("
    "SELECT (f.value->>'note_id') AS note_id FROM jsonb_each(c.fields_notes) f "
    "UNION ALL SELECT c.note_answers->>'note_id'"
    ") src LEFT JOIN notes n ON n.id = CASE WHEN src.note_id ~ '^[0-9]{1,9}$' "
    "THEN CAST(src.note_id AS integer) END "
    "AND n.candidate_id = c.candidate_id AND n.job_id = c.job_id "
    "AND n.kind IN ('card', 'screening_facts') AND n.source_deleted_at IS NULL "
    "WHERE src.note_id ~ '^[0-9]{1,9}$' AND n.id IS NULL) "
    "ORDER BY c.id LIMIT :limit"
)


def enabled() -> bool:
    return bool(settings.RECOMMENDATION_CARD_IMPORT_ENABLED)


async def refresh_candidate(
    db: AsyncSession, *, candidate_id: int, job_id: Optional[int] = None
) -> int:
    """Przelicza karty kandydata: każdą istniejącą i parę ``job_id``."""
    job_ids = {
        row[0]
        for row in (
            await db.execute(_CANDIDATE_CARDS_SQL, {"candidate_id": candidate_id})
        ).all()
    }
    if job_id is not None:
        job_ids.add(job_id)
    changed = 0
    for pair_job_id in sorted(job_ids):
        if await cards.rebuild_pair(db, candidate_id=candidate_id, job_id=pair_job_id):
            changed += 1
            await screening_note_sync.sync_pair_safely(
                db, candidate_id=candidate_id, job_id=pair_job_id
            )
    return changed


async def refresh_candidate_safely(
    db: AsyncSession, *, candidate_id: Optional[int], job_id: Optional[int] = None
) -> None:
    """Wywołanie z zapisu notatki: w savepoincie, nigdy nie cofa notatki."""
    if candidate_id is None or not enabled():
        return
    try:
        async with db.begin_nested():
            await refresh_candidate(db, candidate_id=candidate_id, job_id=job_id)
    except Exception as exc:  # noqa: BLE001 — karta jest dodatkiem do notatki
        logger.warning(
            "recommendation card refresh failed candidate=%s (%s)",
            candidate_id,
            type(exc).__name__,
        )


_RESET_HASH_SQL = text(
    "UPDATE notes SET card_parsed_hash = NULL WHERE candidate_id = :candidate_id "
    "AND kind IN ('card', 'screening_facts')"
)


async def after_candidate_merge(db: AsyncSession, *, survivor_id: int) -> None:
    """Notatki duplikatu są już przepięte — karty ocalałego przeliczą się od nowa."""
    await db.execute(_RESET_HASH_SQL, {"candidate_id": survivor_id})
    await refresh_candidate_safely(db, candidate_id=survivor_id)


async def process_pending(db: AsyncSession, *, limit: int = DEFAULT_BATCH) -> int:
    """Jedna paczka notatek z nieaktualnym odciskiem. Zwraca liczbę notatek."""
    rows = (
        await db.execute(_PENDING_SQL, {"version": str(PARSER_VERSION), "limit": limit})
    ).all()
    if not rows:
        return 0
    seen: set[tuple[int, Optional[int]]] = set()
    for row in rows:
        key = (row.candidate_id, row.job_id)
        if row.candidate_id is None or key in seen:
            continue
        seen.add(key)
        try:
            async with db.begin_nested():
                await refresh_candidate(
                    db, candidate_id=row.candidate_id, job_id=row.job_id
                )
        except Exception as exc:  # noqa: BLE001 — jeden kandydat nie blokuje kolejki
            # Notatka i tak dostaje stempel: bez niego trwały błąd jednej osoby
            # stałby na czele kolejki i zatrzymał import wszystkich pozostałych.
            # Wróci przy zmianie treści albo wersji parsera.
            logger.error(
                "recommendation card import failed candidate=%s job=%s (%s)",
                row.candidate_id,
                row.job_id,
                type(exc).__name__,
            )
    await db.execute(_STAMP_SQL, [{"id": row.id, "hash": row.hash} for row in rows])
    return len(rows)


async def repair_orphans(db: AsyncSession, *, limit: int = DEFAULT_BATCH) -> int:
    """Karty wskazujące na notatkę, której już nie ma. Zwraca liczbę kart."""
    rows = (await db.execute(_ORPHANS_SQL, {"limit": limit})).all()
    for row in rows:
        if await cards.rebuild_pair(
            db, candidate_id=row.candidate_id, job_id=row.job_id
        ):
            await screening_note_sync.sync_pair_safely(
                db, candidate_id=row.candidate_id, job_id=row.job_id
            )
    return len(rows)
