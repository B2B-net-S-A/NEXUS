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
w pamięci procesu (jeden uvicorn) przez ``CACHE_TTL_SECONDS``. Całość
dolicza pętla w tle (``app/tasks/requirement_row_counts.py``); pulpit liczy
w żądaniu tylko to, czego jeszcze nie ma, w limicie ``BUDGET_SECONDS``.
Brak liczby to brak powodu, nie zgadywanie.
"""

from __future__ import annotations

import logging
import time
import unicodedata
from typing import Iterable, Optional, Sequence

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
