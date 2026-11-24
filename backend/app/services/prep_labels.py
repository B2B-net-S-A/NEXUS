"""Nazwy prepów w treściach serwera — lustro ``frontend/src/lib/prep-label.ts``.

F3 planu „Fundamenty prepa” (decyzje Artura z 24.11.2026): przed rozmową
u klienta są trzy spotkania z kandydatem — Przygotowanie (rekruter, fundamenty
i specyfika klienta, ``prep_no`` 0), Prep 1 (Delivery Lead) i Prep 2
(follow-up rekrutera). Numery 1 i 2 zostały, żeby stare prepy, oceny
i ustawienia ocen nie zmieniły znaczenia.

„Przygotowanie” jest rodzaju nijakiego, więc zdań z prepem nie składa się
szablonem ``f"Prep {n}"`` („Przygotowanie zaplanowany”), tylko funkcjami stąd.
"""

from __future__ import annotations

PREPARATION = 0
PREP_NOS = (0, 1, 2)

# (mianownik, w środku zdania, dopełniacz)
_NAMES = {
    0: ("Przygotowanie", "przygotowanie", "przygotowania"),
    1: ("Prep 1", "Prep 1", "Prepu 1"),
    2: ("Prep 2", "Prep 2", "Prepu 2"),
}

STEP_KEYS = {0: "prep0", 1: "prep", 2: "prep2"}


def _names(prep_no: int) -> tuple[str, str, str]:
    return _NAMES.get(prep_no, _NAMES[1])


def name(prep_no: int) -> str:
    """„Przygotowanie”, „Prep 1”, „Prep 2” — na początku zdania i w tytułach."""
    return _names(prep_no)[0]


def in_sentence(prep_no: int) -> str:
    """W środku zdania: „Zaplanuj przygotowanie”, „Zaplanuj Prep 2”."""
    return _names(prep_no)[1]


def genitive(prep_no: int) -> str:
    """Dopełniacz: „brak przygotowania”, „brak Prepu 2”."""
    return _names(prep_no)[2]


def agree(prep_no: int, masculine: str) -> str:
    """Przymiotnik w rodzaju prepu: „zaplanowany” → „zaplanowane” dla Przygotowania."""
    if prep_no != PREPARATION:
        return masculine
    if masculine.endswith("y"):
        return masculine[:-1] + "e"
    if masculine.endswith("i"):
        return masculine + "e"
    return masculine


def with_participle(prep_no: int, masculine: str) -> str:
    """„Przygotowanie zaplanowane”, „Prep 2 zaplanowany”."""
    return f"{name(prep_no)} {agree(prep_no, masculine)}"


def step_key(prep_no: int) -> str:
    """Klucz kroku cyklu rozmowy (``interview_cycle.STEP_KEYS``)."""
    return STEP_KEYS.get(prep_no, "prep")
