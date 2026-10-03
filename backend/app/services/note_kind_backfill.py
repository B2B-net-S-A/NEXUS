"""Uzupełnienie ``notes.kind`` dla wierszy, których nie zapisał ORM.

Dwa źródła takich wierszy: notatki sprzed migracji 0412 i promocja aktywności
Traffita (jeden ``INSERT ... SELECT`` w surowym SQL — nasłuch modelu go nie
widzi). Reguła jest ta sama co przy zapisie: ``note_kinds.classify``.

``UPDATE`` idzie surowym SQL i nie rusza ``updated_at`` — na tej kolumnie stoi
odcisk nocnego odczytu faktów, a jej zmiana kazałaby zapłacić za odczyt
każdego kandydata jeszcze raz.
"""

from __future__ import annotations

from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import note_kinds

DEFAULT_BATCH = 2000

_PENDING_SQL = text(
    "SELECT id, content, note_type::text, external_source FROM notes "
    "WHERE kind IS NULL ORDER BY id LIMIT :lim"
)
_UPDATE_SQL = text(
    "UPDATE notes SET kind = :kind WHERE id = ANY(:ids) AND kind IS NULL"
)


_BY_IDS_SQL = text(
    "SELECT id, content, note_type::text, external_source FROM notes "
    "WHERE id = ANY(:ids) AND kind IS NULL"
)


async def _apply(db: AsyncSession, rows) -> int:
    by_kind: dict[str, list[int]] = defaultdict(list)
    for note_id, content, note_type, external_source in rows:
        kind = note_kinds.classify(
            content, note_type=note_type, external_source=external_source
        )
        by_kind[kind].append(note_id)
    for kind, ids in by_kind.items():
        await db.execute(_UPDATE_SQL, {"kind": kind, "ids": ids})
    return len(rows)


async def classify_notes(db: AsyncSession, note_ids: list[int]) -> int:
    """Nadaje rodzaj wskazanym notatkom (świeżo wstawionym surowym SQL)."""
    done = 0
    for start in range(0, len(note_ids), DEFAULT_BATCH):
        chunk = note_ids[start : start + DEFAULT_BATCH]
        rows = (await db.execute(_BY_IDS_SQL, {"ids": chunk})).all()
        done += await _apply(db, rows)
    return done


async def classify_pending(db: AsyncSession, *, limit: int = DEFAULT_BATCH) -> int:
    """Nadaje rodzaj najwyżej ``limit`` notatkom bez rodzaju; zwraca ich liczbę.

    Nie commituje — robi to wołający (import Traffita w swojej transakcji,
    pętla startowa po każdej paczce).
    """
    rows = (await db.execute(_PENDING_SQL, {"lim": limit})).all()
    return await _apply(db, rows)
