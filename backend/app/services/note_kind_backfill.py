"""Uzupełnienie ``notes.kind`` dla wierszy, których nie zapisał ORM.

Dwa źródła takich wierszy: notatki sprzed migracji 0412 i promocja aktywności
Traffita (jeden ``INSERT ... SELECT`` w surowym SQL — nasłuch modelu go nie
widzi). Reguła jest ta sama co przy zapisie: ``note_kinds.classify``.

``UPDATE`` idzie surowym SQL i nie rusza ``updated_at`` — na tej kolumnie stoi
odcisk nocnego odczytu faktów, a jej zmiana kazałaby zapłacić za odczyt
każdego kandydata jeszcze raz.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Optional

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


# ── jednorazowo: dłuższe wpisy Delivery Leada o cenie (03.10.2026) ───────────
#
# Reguła `dl_rate` kończyła się na 200 znakach, a „Pokazujemy za 178 zł na:
# <lista rekrutacji>” bywa dłuższe przez same tytuły. Pomiar na produkcji:
# 142 takie wpisy miały inny rodzaj, więc rekruter widział w nich stawkę do
# klienta, a modele czytały je jak zwykłą notatkę. Reguła ma teraz wyższy
# limit dla tej formy; ten krok przelicza wiersze zapisane starą regułą.

DL_RATE_LISTS_MARKER = "note_kind_dl_rate_lists_2026_10"

# Zgrubny filtr w SQL (wielkie litery ze znakiem diakrytycznym wprost, bo
# ctype bazy to `C`); o rodzaju rozstrzyga i tak `note_kinds.classify`.
_DL_RATE_VERBS = "(wy[sśŚ][lłŁ]ijmy|pokazujemy|poka[zżŻ]my)"
_MARKER_SQL = text("SELECT 1 FROM app_settings WHERE key = :key")
_DL_RATE_CANDIDATES_SQL = text(
    "SELECT id, kind, content, note_type::text, external_source FROM notes "
    "WHERE kind IS NOT NULL AND kind <> :dl_rate AND content ~* :verbs ORDER BY id"
)
_SET_KIND_SQL = text(
    "UPDATE notes SET kind = :kind WHERE id = ANY(:ids) AND kind <> :kind"
)
_STORE_MARKER_SQL = text(
    "INSERT INTO app_settings (key, value) VALUES (:key, CAST(:value AS jsonb)) "
    "ON CONFLICT (key) DO NOTHING"
)


async def reclassify_dl_rate_lists(db: AsyncSession) -> Optional[int]:
    """Przelicza rodzaj dłuższych wpisów o cenie; ``None``, gdy już zrobione.

    Zmienia wyłącznie wiersze, które nowa reguła uznaje za ``dl_rate``,
    i nie rusza ``updated_at``. Paragon niesie same id i poprzedni rodzaj —
    to wystarcza do odwrócenia. Nie commituje.
    """
    if await db.scalar(_MARKER_SQL, {"key": DL_RATE_LISTS_MARKER}):
        return None
    rows = (
        await db.execute(
            _DL_RATE_CANDIDATES_SQL,
            {"dl_rate": note_kinds.DL_RATE, "verbs": _DL_RATE_VERBS},
        )
    ).all()
    previous: dict[str, list[int]] = defaultdict(list)
    for note_id, kind, content, note_type, external_source in rows:
        new_kind = note_kinds.classify(
            content, note_type=note_type, external_source=external_source
        )
        if new_kind == note_kinds.DL_RATE:
            previous[kind].append(note_id)
    ids = [note_id for group in previous.values() for note_id in group]
    if ids:
        await db.execute(_SET_KIND_SQL, {"kind": note_kinds.DL_RATE, "ids": ids})
    await db.execute(
        _STORE_MARKER_SQL,
        {
            "key": DL_RATE_LISTS_MARKER,
            "value": json.dumps({"changed": len(ids), "previous_kind": previous}),
        },
    )
    return len(ids)
