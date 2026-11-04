"""Suma kontrolna timesheetu — dokładny odpowiednik funkcji Compassa.

Compass (``lib/hr/timesheet-hash.ts``, ``computeTimesheetHash``) liczy SHA-256
z kanonicznej postaci wpisów i zapisuje ją przy akceptacji w ``pdf_hash``.
Pobranie PDF porównuje sumę bieżących wpisów z zapisaną; rozjazd = 409.
Ta sama funkcja musi dawać ten sam wynik dla tych samych wpisów, bo timesheety
zaakceptowane w Compassie przechodzą do NEXUSA razem ze swoją sumą — inaczej
każdy zaimportowany PDF zgłaszałby rozbieżność. Wektory referencyjne
(policzone, wykonując funkcję Compassa) przypina ``tests/test_hr_time_hash.py``.

Algorytm (1:1 z TypeScriptem):

1. sortowanie po ``work_date`` (tekst ISO), a w obrębie dnia po napisie
   ``f"{Number(hours)}|{project ?? ''}|{description}"`` porównywanym jak
   w JavaScripcie (jednostki UTF-16, więc „12|…” < „2.5|…”),
2. wiersz ``f"{work_date}|{hours.toFixed(2)}|{project ?? ''}|{description}"``,
3. wiersze złączone ``\\n``, SHA-256 z UTF-8, zapis szesnastkowy małymi literami.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Optional, Union

Hours = Union[Decimal, int, float, str]


@dataclass(frozen=True)
class HashEntry:
    work_date: Union[date, str]
    hours: Hours
    project: Optional[str]
    description: str


def _decimal(value: Hours) -> Decimal:
    if isinstance(value, Decimal):
        return value
    # float przez str: 7.25 → Decimal("7.25"), nie rozwinięcie binarne
    return Decimal(str(value))


def js_number_text(value: Hours) -> str:
    """``String(Number(x))`` z JavaScriptu dla godzin (0–24, dwa miejsca)."""

    number = _decimal(value)
    if number == 0:
        return "0"
    return format(number.normalize(), "f")


def js_to_fixed_2(value: Hours) -> str:
    """``Number(x).toFixed(2)`` — przy NUMERIC(4,2) wynik jest dokładny."""

    return str(_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _iso(day: Union[date, str]) -> str:
    return day.isoformat() if isinstance(day, date) else str(day)


def _js_order(text: str) -> bytes:
    # Porównanie napisów w JS idzie po jednostkach UTF-16; bajty UTF-16BE
    # porządkują się dokładnie tak samo (Python porównuje punkty kodowe).
    return text.encode("utf-16-be", "surrogatepass")


def canonical_text(entries: Iterable[HashEntry]) -> str:
    rows = [
        (
            _iso(entry.work_date),
            f"{js_number_text(entry.hours)}|{entry.project or ''}|{entry.description}",
            entry,
        )
        for entry in entries
    ]
    rows.sort(key=lambda row: (_js_order(row[0]), _js_order(row[1])))
    return "\n".join(
        f"{day}|{js_to_fixed_2(entry.hours)}|{entry.project or ''}|{entry.description}"
        for day, _, entry in rows
    )


def compute_timesheet_hash(entries: Iterable[HashEntry]) -> str:
    return hashlib.sha256(canonical_text(entries).encode("utf-8")).hexdigest()
