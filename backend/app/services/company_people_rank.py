"""Kolejność osób w „Kogo znamy”: kto ma decyzję i czy CV nie jest stare.

Reguła z makiety M7 (P8, 09.11.2026). Bez modelu AI, bo stanowisko z CV
to tekst od kandydata, a kolejność ma być powtarzalna i tania.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

_DECISION_WORDS = re.compile(
    r"(?:^|\W)(?:head|dyrektor|director|cto|cio|ciso|vp|kierownik|manager|menedżer|lead)"
    r"(?:\W|$)",
    re.IGNORECASE,
)
# Tytuł z „manager” bez decyzji o zakupie oraz osoby na początku drogi. „Intern”
# ma granicę słowa, bo „Internal Audit Manager” to rola decyzyjna.
_NOT_DECISION = re.compile(
    r"project manager|test manager|product owner|account|sprzeda|placówk|oddział|sklep"
    r"|staż|stazyst|praktyk|\bintern\b|trainee|junior|młodsz|mlodsz",
    re.IGNORECASE,
)

#: Po ilu latach od dodania do bazy CV dostaje znacznik „CV sprzed 3 lat”.
STALE_CV_YEARS = 3


def is_decision_role(title: Optional[str]) -> bool:
    """Czy stanowisko z CV wskazuje osobę z wpływem na decyzję."""
    if not title:
        return False
    return bool(_DECISION_WORDS.search(title)) and not _NOT_DECISION.search(title)


def cv_is_stale(added: Optional[date], today: date) -> bool:
    """Osoba trafiła do bazy ponad ``STALE_CV_YEARS`` lata temu."""
    if added is None:
        return False
    try:
        limit = today.replace(year=today.year - STALE_CV_YEARS)
    except ValueError:  # 29 lutego, a trzy lata wstecz takiego dnia nie ma
        limit = today.replace(year=today.year - STALE_CV_YEARS, day=28)
    return added < limit
