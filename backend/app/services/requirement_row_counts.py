"""Ile osób w bazie ma słowo wiersza wymagań — licznik „W bazie” po stronie serwera.

Edytor wierszy (`frontend/src/lib/requirement-rows-api.ts`, `countPeople`)
liczy wiersz listą kandydatów: aktywni i pasywni, słowa wiersza jako jedna
grupa LUB (`q_any_group`), słowa „Wyklucz” jako `q_none`, wspólna semantyka
(całe słowo). Tu idzie to samo zapytanie (`_build_candidate_filtered_query`),
bo „Wymagania do poprawy” (powód `rare_word`) muszą mówić to, co DL zobaczy
po otwarciu edytora.

Koszt (pomiar 27.10.2026 na kopii z 22.10): rzadkie słowo liczy się w
0,02–0,5 s, popularne do 2,7 s nawet z ``LIMIT``; 673 wiersze otwartych
rekrutacji to ok. 7 min. Interesuje nas tylko „mniej niż
``RARE_WORD_PEOPLE``”, więc liczymy do tej granicy, a wynik trzymamy
w pamięci procesu przez ``CACHE_TTL_SECONDS``, z kopią wspólną dla procesów
w ``app_settings`` (``load_shared`` / ``save_shared``, tylko pętla). Całość
dolicza pętla w tle (``app/tasks/requirement_row_counts.py``); pulpit liczy
w żądaniu tylko to, czego jeszcze nie ma, w limicie ``BUDGET_SECONDS``.
Brak liczby to brak powodu, nie zgadywanie.
"""

from __future__ import annotations

import json
import logging
import time
import unicodedata
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Lustro `RARE_WORD_PEOPLE` z `frontend/src/lib/requirement-rows.ts`.
RARE_WORD_PEOPLE = 20
CACHE_TTL_SECONDS = 24 * 3600
# Pętla w tle liczy ponownie wpisy, którym zostało mniej niż tyle życia.
REFRESH_BEFORE_SECONDS = 3 * 3600
BUDGET_SECONDS = 1.5

Key = tuple[tuple[str, ...], tuple[str, ...]]

_cache: dict[Key, tuple[Optional[int], float]] = {}


def _fold(word: str) -> str:
    return " ".join(unicodedata.normalize("NFC", word).casefold().split())


def key(words: Sequence[str], exclude: Sequence[str]) -> Key:
    return (
        tuple(_fold(w) for w in words),
        tuple(sorted({_fold(w) for w in exclude if w.strip()})),
    )


def lookup(k: Key, *, fresh_for: float = 0.0) -> tuple[bool, Optional[int]]:
    """``(jest w pamięci, liczba)``; liczba ``None`` = lista odmówiła (np. „C”).

    ``fresh_for`` — wpis, który wygaśnie wcześniej, liczy się jak brak."""
    hit = _cache.get(k)
    if hit is None or hit[1] < time.monotonic() + fresh_for:
        return False, None
    return True, hit[0]


def cached(words: Sequence[str], exclude: Sequence[str]) -> Optional[int]:
    """Liczba z pamięci albo ``None`` — domyślny licznik ``build_proposal``."""
    return lookup(key(words, exclude))[1]


async def count_row(
    db: AsyncSession, words: Sequence[str], exclude: Sequence[str]
) -> Optional[int]:
    """Osoby z którymkolwiek słowem wiersza, najwyżej ``RARE_WORD_PEOPLE``.

    ``None``, gdy lista kandydatów odrzuca słowa (422 — słowo krótsze niż
    2 znaki), jak „nie policzono” w edytorze.
    """
    from fastapi import HTTPException
    from sqlalchemy import func, select

    from app.api.candidates import CandidateFilterSpec, _build_candidate_filtered_query
    from app.models.candidate import Candidate, CandidateStatus

    spec = CandidateFilterSpec(
        status=[CandidateStatus.active, CandidateStatus.passive],
        q_any_group=["|".join(words)],
        q_none=list(exclude) or None,
        semantics_version=2,
    )
    try:
        query, _ = await _build_candidate_filtered_query(db, spec)
    except HTTPException:
        return None
    ids = query.with_only_columns(Candidate.id).limit(RARE_WORD_PEOPLE).subquery()
    return int(await db.scalar(select(func.count()).select_from(ids)) or 0)


async def ensure(
    db: AsyncSession,
    rows: Iterable[tuple[Sequence[str], Sequence[str]]],
    *,
    deadline: float,
    fresh_for: float = 0.0,
) -> int:
    """Policz wiersze, których nie ma w pamięci, dopóki nie minie ``deadline``
    (``time.monotonic()``). Błąd jednego wiersza nie zatrzymuje reszty.
    Oddaje liczbę policzonych wierszy."""
    seen: set[Key] = set()
    done = 0
    for words, exclude in rows:
        k = key(words, exclude)
        if k in seen or lookup(k, fresh_for=fresh_for)[0]:
            continue
        seen.add(k)
        if time.monotonic() >= deadline:
            return done
        try:
            async with db.begin_nested():
                people = await count_row(db, words, exclude)
        except Exception:  # noqa: BLE001 — bez liczby nie ma powodu, pulpit działa
            logger.warning("requirement_row_counts: nie policzono %r", words)
            continue
        _cache[k] = (people, time.monotonic() + CACHE_TTL_SECONDS)
        done += 1
    return done


def clear() -> None:
    _cache.clear()


# Wspólna kopia pamięci w `app_settings` (26.11.2026). Każdy proces web
# zaczynał z pustą pamięcią, a procesy w kontenerze wstają na nowo po każdym
# padnięciu, nie tylko po wdrożeniu: zapytanie liczące szło na produkcji
# ok. 28 tys. razy w 23 h (ok. 6 580 s bazy) przy ok. 540 wierszach na obrót.
# Czyta i zapisuje ją tylko pętla w tle; trasy dalej czytają pamięć procesu.
SHARED_KEY = "requirement_row_counts"

_SAVE_SQL = text(
    "INSERT INTO app_settings (key, value, updated_at) "
    "VALUES (:key, jsonb_build_object('entries', CAST(:entries AS jsonb)), now()) "
    "ON CONFLICT (key) DO UPDATE SET updated_at = now(), "
    "value = jsonb_build_object('entries', ("
    "SELECT coalesce(jsonb_object_agg(k, v), '{}'::jsonb) FROM ("
    "SELECT DISTINCT ON (k) k, v FROM ("
    "SELECT key AS k, value AS v FROM jsonb_each("
    "coalesce(app_settings.value -> 'entries', '{}'::jsonb)) "
    "UNION ALL SELECT key, value FROM jsonb_each(CAST(:entries AS jsonb))) AS merged "
    "WHERE (v ->> 1)::float8 > :now ORDER BY k, (v ->> 1)::float8 DESC) AS latest))"
)


def _shared_key(k: Key) -> str:
    return json.dumps([list(k[0]), list(k[1])], ensure_ascii=False)


async def load_shared(db: AsyncSession) -> int:
    """Dołóż do pamięci wpisy z kopii wspólnej (dłuższe życie wygrywa).
    Oddaje liczbę wpisów, które przybyły albo się przedłużyły."""
    value = await db.scalar(
        text("SELECT value FROM app_settings WHERE key = :key"), {"key": SHARED_KEY}
    )
    entries = (value or {}).get("entries") or {}
    wall, mono = time.time(), time.monotonic()
    added = 0
    for raw, (people, expires_at) in entries.items():
        left = float(expires_at) - wall
        if left <= 0:
            continue
        words, exclude = json.loads(raw)
        k = (tuple(words), tuple(exclude))
        hit = _cache.get(k)
        if hit is None or hit[1] < mono + left:
            _cache[k] = (people, mono + left)
            added += 1
    return added


async def save_shared(db: AsyncSession) -> int:
    """Zapisz pamięć procesu do kopii wspólnej; wygasłe wpisy z niej znikają.
    Zatwierdza wywołujący."""
    wall, mono = time.time(), time.monotonic()
    entries = {
        _shared_key(k): [people, wall + (expires - mono)]
        for k, (people, expires) in _cache.items()
        if expires > mono
    }
    if not entries:
        return 0
    await db.execute(
        _SAVE_SQL,
        {
            "key": SHARED_KEY,
            "entries": json.dumps(entries, ensure_ascii=False),
            "now": wall,
        },
    )
    return len(entries)
