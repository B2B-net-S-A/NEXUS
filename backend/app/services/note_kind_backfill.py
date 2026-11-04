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
from app.services.client_rate_notes import DL_PAIR_AUTHOR_SQL, DL_PAIR_SQL_PATTERN

DEFAULT_BATCH = 2000

# Autor rozstrzyga o parze „X/Y” (``note_kinds.with_author``), więc odczyt
# niesie jego rolę — tym samym wyrażeniem co plan stawki do klienta.
_SELECT_WITH_AUTHOR = (
    "SELECT n.id, n.content, n.note_type::text, n.external_source, "
    f"{DL_PAIR_AUTHOR_SQL} AS author_is_dl "
    "FROM notes n LEFT JOIN users u ON u.id = n.author_id "
)
_PENDING_SQL = text(
    _SELECT_WITH_AUTHOR + "WHERE n.kind IS NULL ORDER BY n.id LIMIT :lim"
)
_UPDATE_SQL = text(
    "UPDATE notes SET kind = :kind WHERE id = ANY(:ids) AND kind IS NULL"
)


_BY_IDS_SQL = text(_SELECT_WITH_AUTHOR + "WHERE n.id = ANY(:ids) AND n.kind IS NULL")


async def _apply(db: AsyncSession, rows) -> int:
    by_kind: dict[str, list[int]] = defaultdict(list)
    for note_id, content, note_type, external_source, author_is_dl in rows:
        kind = note_kinds.classify(
            content,
            note_type=note_type,
            external_source=external_source,
            author_is_dl=bool(author_is_dl),
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


# ── jednorazowo: wpisy „X/Y” Delivery Leada w zwykłych notatkach (07.10.2026) ─
#
# Od #2062 plan stawki do klienta czyta krótki wpis „X/Y” (X — stawka do
# klienta) także ze zwykłej notatki, gdy pisał ją Delivery Lead albo admin —
# a rekruter widział taką notatkę w całości, bo zakrywanie działa tylko dla
# ``dl_rate``. Pomiar na produkcji 07.10.2026: 309 notatek (216 kandydatów).
# Nowe notatki dostają ``dl_rate`` przy zapisie (``note_kinds.with_author``);
# ten krok przelicza wiersze zapisane wcześniej.

DL_PAIR_HUMAN_MARKER = "note_kind_dl_pair_human_2026_10"
# Kandydaci, których zapisane podsumowania usunięto — klucz innego kształtu
# niż paragon (publiczny odczyt paragonów migracji go nie drukuje).
DL_PAIR_HUMAN_DETAILS_KEY = "repair_details_note_kind_dl_pair_human_2026_10"

_DL_PAIR_HUMAN_CANDIDATES_SQL = text(
    "SELECT n.id, n.candidate_id, n.content, n.note_type::text, n.external_source "
    "FROM notes n JOIN users u ON u.id = n.author_id "
    f"WHERE n.kind = :human AND n.content ~ :pattern AND {DL_PAIR_AUTHOR_SQL} "
    "ORDER BY n.id"
)
_SET_DL_RATE_FROM_HUMAN_SQL = text(
    "UPDATE notes SET kind = :dl_rate WHERE id = ANY(:ids) AND kind = :human"
)
# Podsumowanie aktywności tych kandydatów mogło powstać z notatek, których
# model już nie czyta (``dl_rate`` jest poza AI) — usuwamy tylko je, zamiast
# unieważniać wszystkie podbiciem wersji zakresu. Następne „Odśwież” liczy je
# od nowa.
_DROP_SUMMARIES_SQL = text(
    "DELETE FROM candidate_activity_summaries WHERE candidate_id = ANY(:ids)"
)


async def _hide_bell_snippets(db: AsyncSession, note_ids: list[int]) -> int:
    """Dzwonki wzmianek i odpowiedzi tych notatek pokazywały „150/110” każdemu
    oznaczonemu — także rekruterowi. Ten sam fragment co przy nowym zapisie."""
    from sqlalchemy import update

    from app.models.notification import Notification
    from app.services.mention_dispatch import NOTE_SNIPPET_NOTIFICATION_TYPES

    result = await db.execute(
        update(Notification)
        .where(
            Notification.notification_type.in_(NOTE_SNIPPET_NOTIFICATION_TYPES),
            Notification.related_entity_type == "note",
            Notification.related_entity_id.in_(note_ids),
        )
        .values(message=note_kinds.CLIENT_RATE_SNIPPET)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


async def reclassify_dl_pair_human_notes(db: AsyncSession) -> Optional[int]:
    """Zwykłe notatki z parą „X/Y” DL-a/admina → ``dl_rate``; ``None``, gdy
    już zrobione.

    Ta sama reguła co przy zapisie (``note_kinds.classify`` z autorem). Nie
    rusza ``updated_at``. Zakrywa też fragment w dzwonkach wzmianek tych
    notatek i usuwa zapisane podsumowania aktywności ich kandydatów. Paragon: liczby i id notatek (wystarczają do
    odwrócenia — poprzedni rodzaj to zawsze ``human``). Nie commituje.
    """
    if await db.scalar(_MARKER_SQL, {"key": DL_PAIR_HUMAN_MARKER}):
        return None
    rows = (
        await db.execute(
            _DL_PAIR_HUMAN_CANDIDATES_SQL,
            {"human": note_kinds.HUMAN, "pattern": DL_PAIR_SQL_PATTERN},
        )
    ).all()
    ids: list[int] = []
    candidate_ids: set[int] = set()
    for note_id, candidate_id, content, note_type, external_source in rows:
        kind = note_kinds.classify(
            content,
            note_type=note_type,
            external_source=external_source,
            author_is_dl=True,
        )
        if kind == note_kinds.DL_RATE:
            ids.append(note_id)
            if candidate_id is not None:
                candidate_ids.add(candidate_id)
    summaries = 0
    bell_snippets = 0
    if ids:
        await db.execute(
            _SET_DL_RATE_FROM_HUMAN_SQL,
            {"dl_rate": note_kinds.DL_RATE, "human": note_kinds.HUMAN, "ids": ids},
        )
        bell_snippets = await _hide_bell_snippets(db, ids)
    if candidate_ids:
        result = await db.execute(_DROP_SUMMARIES_SQL, {"ids": sorted(candidate_ids)})
        summaries = result.rowcount or 0
    await db.execute(
        _STORE_MARKER_SQL,
        {
            "key": DL_PAIR_HUMAN_MARKER,
            "value": json.dumps(
                {
                    "changed": len(ids),
                    "previous_kind": note_kinds.HUMAN,
                    "note_ids": ids,
                    "candidates": len(candidate_ids),
                    "summaries_deleted": summaries,
                    "bell_snippets_hidden": bell_snippets,
                }
            ),
        },
    )
    await db.execute(
        _STORE_MARKER_SQL,
        {
            "key": DL_PAIR_HUMAN_DETAILS_KEY,
            "value": json.dumps(
                {"note_ids": ids, "candidate_ids": sorted(candidate_ids)}
            ),
        },
    )
    return len(ids)
