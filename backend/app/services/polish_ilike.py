"""Wyszukiwanie tekstowe w SQL bez wrażliwości na polskie znaki.

Produkcja nie ma rozszerzenia ``unaccent``, a musl w ``postgres:16-alpine``
nie implementuje kolacji — dlatego fold robimy ``translate()`` tą samą mapą,
której używa pełnotekstowa wyszukiwarka kandydatów
(``advanced_candidate_search.fold_polish`` / kolumna
``candidates.search_doc_unaccented``, migracja 0159). Jedna mapa w całej
aplikacji: „krakow" znajduje „Kraków", „spolka" znajduje „Spółka".

Zapytanie foldujemy WYŁĄCZNIE mapą polskich liter (bez ``lower()``) — o wielkość
liter dba ``ILIKE``, a znaki spoza mapy zostają nietknięte po obu stronach.
Mapa jest 1:1 i zachowuje długość, więc dopasowanie z foldem jest nadzbiorem
dotychczasowego ``ILIKE`` na surowej wartości — nic, co było znajdowane, nie
znika.
"""

from __future__ import annotations

import unicodedata

from sqlalchemy import func
from sqlalchemy.sql import ColumnElement

from app.services.advanced_candidate_search import (
    _POLISH_FOLD_DST,
    _POLISH_FOLD_MAP,
    _POLISH_FOLD_SRC,
)


def fold_polish_query(value: str) -> str:
    """Zdejmuje polskie znaki z frazy (NFC → mapa), bez zmiany wielkości liter."""
    return unicodedata.normalize("NFC", value).translate(_POLISH_FOLD_MAP)


def escape_like(value: str) -> str:
    """Znaki wieloznaczne LIKE (``%``, ``_``, ``\\``) traktowane dosłownie."""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def folded_contains_pattern(value: str) -> str:
    """Wzorzec ``%fraza%`` po foldzie i escapowaniu — do ``polish_folded_ilike``."""
    return f"%{escape_like(fold_polish_query(value))}%"


def polish_folded(expr) -> ColumnElement:
    """Wyrażenie SQL: wartość kolumny bez polskich znaków (wielkość liter bez zmian)."""
    return func.translate(expr, _POLISH_FOLD_SRC, _POLISH_FOLD_DST)


def polish_folded_ilike(expr, value: str) -> ColumnElement:
    """``expr`` zawiera ``value``, bez wrażliwości na wielkość liter i polskie znaki."""
    return polish_folded(expr).ilike(folded_contains_pattern(value), escape="\\")
