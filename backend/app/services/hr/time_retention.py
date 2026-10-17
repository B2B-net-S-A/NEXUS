"""Archiwum potwierdzeń godzin na zleceniu (etap 2, D7, 17.10.2026).

Ustawa o minimalnym wynagrodzeniu za pracę: zleceniobiorca potwierdza liczbę
przepracowanych godzin (art. 8b), a zleceniodawca przechowuje te dokumenty
3 lata od dnia, w którym wynagrodzenie stało się wymagalne (art. 8c). Przyjęty
raport godzin osoby na zleceniu („Potwierdzenie godzin”) jest takim
dokumentem.

Termin wypłaty liczymy jako koniec miesiąca następnego po rozliczanym (umowy
firmy płacą do końca kolejnego miesiąca). Do tego dnia przyjęte potwierdzenie
można jeszcze poprawić (cofnąć przyjęcie, zgłoszona nieobecność przelicza
godziny) — to zwykła korekta przed wypłatą. Po terminie, przez 3 lata,
potwierdzenie stoi bez zmian: cofnięcie przyjęcia i usunięcie wpisu dają 409,
a przeliczenie godzin po zgłoszonej nieobecności pomija miesiąc (jak miesiąc
zamknięty w płacach — osoba dostaje ostrzeżenie, Płace powiadomienie).

Wiersza timesheetu nie usuwa żadna ścieżka NEXUSA (``timesheets.user_id`` ma
``ON DELETE RESTRICT``, odejście i wyłączenie konta nie kasują godzin), więc
strażnik pilnuje zmian, nie kasowania całego miesiąca.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from app.core.scheduling import business_today

RETENTION_YEARS = 3
MANDATE_FORM = "zlecenie"

_MONTH_NAMES = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


def payment_due(year: int, month: int) -> date:
    """Ostatni dzień miesiąca następnego po rozliczanym (termin wypłaty)."""

    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(next_year, next_month, calendar.monthrange(next_year, next_month)[1])


def retention_until(year: int, month: int) -> date:
    """Do kiedy włącznie potwierdzenie godzin musi zostać bez zmian."""

    due = payment_due(year, month)
    target_year = due.year + RETENTION_YEARS
    last = calendar.monthrange(target_year, due.month)[1]
    return date(target_year, due.month, min(due.day, last))


def frozen(
    *,
    employment_type: Optional[str],
    status: str,
    year: int,
    month: int,
    today: Optional[date] = None,
) -> bool:
    """Przyjęte potwierdzenie godzin zlecenia po terminie wypłaty, w okresie 3 lat."""

    if employment_type != MANDATE_FORM or status != "approved":
        return False
    day = today or business_today()
    return payment_due(year, month) < day <= retention_until(year, month)


def _label(year: int, month: int) -> str:
    return f"{_MONTH_NAMES[month - 1]} {year}"


def revoke_refusal(
    *,
    employment_type: Optional[str],
    status: str,
    year: int,
    month: int,
    today: Optional[date] = None,
) -> Optional[str]:
    """Powód odmowy cofnięcia przyjęcia (``None`` = wolno cofnąć)."""

    if not frozen(
        employment_type=employment_type,
        status=status,
        year=year,
        month=month,
        today=today,
    ):
        return None
    return (
        f"Potwierdzenie godzin za {_label(year, month)} jest już podstawą wypłaty "
        f"(termin {payment_due(year, month):%d.%m.%Y}) — NEXUS przechowuje je "
        f"bez zmian do {retention_until(year, month):%d.%m.%Y} (art. 8c ustawy "
        "o minimalnym wynagrodzeniu). Korektę zrobią Płace."
    )


def delete_refusal(
    *,
    employment_type: Optional[str],
    status: str,
    year: int,
    month: int,
    today: Optional[date] = None,
) -> Optional[str]:
    """Powód odmowy usunięcia wpisu z potwierdzenia (``None`` = wolno)."""

    if not frozen(
        employment_type=employment_type,
        status=status,
        year=year,
        month=month,
        today=today,
    ):
        return None
    return (
        f"Wpisy potwierdzenia godzin za {_label(year, month)} zostają bez zmian "
        f"do {retention_until(year, month):%d.%m.%Y} (art. 8c ustawy o minimalnym "
        "wynagrodzeniu)."
    )


__all__ = [
    "RETENTION_YEARS",
    "delete_refusal",
    "frozen",
    "payment_due",
    "retention_until",
    "revoke_refusal",
]
