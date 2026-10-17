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

O ochronie decyduje forma z miesiąca dokumentu, nie obecna forma osoby:
akceptacja zapisuje ją w ``timesheets.employment_type`` (``document_form``),
więc potwierdzenie z czasu zlecenia zostaje w archiwum także po zmianie formy
na B2B. Stare wiersze bez zapisanej formy liczą się obecną formą.
"""

from __future__ import annotations

import calendar
from datetime import date
from typing import Optional

from app.core.scheduling import business_today
from app.models.hr_time import Timesheet
from app.services.hr.payroll_periods import label

RETENTION_YEARS = 3
MANDATE_FORM = "zlecenie"


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


def document_form(timesheet: Timesheet, current_form: Optional[str]) -> Optional[str]:
    """Forma, w której przyjęto dokument; bez zapisanej (stare wiersze) — obecna."""

    return timesheet.employment_type or current_form


def sheet_frozen(
    timesheet: Timesheet,
    *,
    current_form: Optional[str],
    today: Optional[date] = None,
) -> bool:
    """``frozen`` dla timesheetu — forma z miesiąca dokumentu (``document_form``)."""

    return frozen(
        employment_type=document_form(timesheet, current_form),
        status=timesheet.status,
        year=timesheet.year,
        month=timesheet.month,
        today=today,
    )


def revoke_refusal(
    timesheet: Timesheet,
    *,
    current_form: Optional[str],
    today: Optional[date] = None,
) -> Optional[str]:
    """Powód odmowy cofnięcia przyjęcia (``None`` = wolno cofnąć)."""

    if not sheet_frozen(timesheet, current_form=current_form, today=today):
        return None
    year, month = timesheet.year, timesheet.month
    return (
        f"Potwierdzenie godzin za {label(year, month)} jest już podstawą wypłaty "
        f"(termin {payment_due(year, month):%d.%m.%Y}) — NEXUS przechowuje je "
        f"bez zmian do {retention_until(year, month):%d.%m.%Y} (art. 8c ustawy "
        "o minimalnym wynagrodzeniu). Korektę zrobią Płace."
    )


def delete_refusal(
    timesheet: Timesheet,
    *,
    current_form: Optional[str],
    today: Optional[date] = None,
) -> Optional[str]:
    """Powód odmowy usunięcia wpisu z potwierdzenia (``None`` = wolno)."""

    if not sheet_frozen(timesheet, current_form=current_form, today=today):
        return None
    year, month = timesheet.year, timesheet.month
    return (
        f"Wpisy potwierdzenia godzin za {label(year, month)} zostają bez zmian "
        f"do {retention_until(year, month):%d.%m.%Y} (art. 8c ustawy o minimalnym "
        "wynagrodzeniu)."
    )


__all__ = [
    "RETENTION_YEARS",
    "delete_refusal",
    "document_form",
    "frozen",
    "payment_due",
    "retention_until",
    "revoke_refusal",
    "sheet_frozen",
]
