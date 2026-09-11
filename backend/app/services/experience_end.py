"""Kiedy wpis doświadczenia z CV opisuje pracę OBECNĄ — jedna reguła dla repo.

``experience[*].end`` bywa pusty (kanoniczny znacznik bieżącej pracy — patrz
``_current_company_predicate`` w ``app/api/candidates.py``) albo SŁOWNY:
parsery CV i ręczne wpisy zostawiają „present", „current", „obecnie", „teraz".
Taki wpis to praca obecna, nie przeszła. Do 09.2026 wiedział o tym tylko
szybki podgląd kandydata (``candidate_quick_view``); filtr listy „Poprzednia
firma" i ATLAS (``/api/integrations/companies/people``) czytały każdy niepusty
``end`` jako datę zakończenia, więc osoba pracująca dziś u klienta trafiała do
„byłych pracowników".

Porównanie jest po przycięciu i bez rozróżniania wielkości liter.
"""

from __future__ import annotations

import re

# Pusty napis (także same spacje) to brak daty zakończenia.
CURRENT_END_MARKERS: frozenset[str] = frozenset(
    {"", "present", "current", "obecnie", "teraz"}
)

# Wyłącznie znaczniki SŁOWNE. W SQL-u filtra „Poprzednia firma" pusty `end`
# ma własną, historyczną regułę pozycji (wpis dalej niż na pierwszej pozycji
# liczy się jako przeszły nawet bez daty) — słowo „obecnie" tę regułę wyłącza.
CURRENT_END_WORDS: frozenset[str] = CURRENT_END_MARKERS - {""}

# Znaczniki trafiają do SQL-a jako literały — pilnujemy, że to same litery.
if not all(re.fullmatch(r"[a-z]+", word) for word in CURRENT_END_WORDS):
    raise RuntimeError("CURRENT_END_WORDS must be plain lowercase ASCII words")


def is_current_end(value: object) -> bool:
    """Czy ``end`` wpisu doświadczenia znaczy „pracuje tam nadal"."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().casefold() in CURRENT_END_MARKERS
    return False


def sql_current_end_literals(*, include_empty: bool) -> str:
    """Lista literałów do ``IN (...)`` — porównywana z ``lower(btrim(end, białe znaki))``."""
    words = sorted(CURRENT_END_MARKERS if include_empty else CURRENT_END_WORDS)
    return ", ".join(f"'{word}'" for word in words)


__all__ = [
    "CURRENT_END_MARKERS",
    "CURRENT_END_WORDS",
    "is_current_end",
    "sql_current_end_literals",
]
