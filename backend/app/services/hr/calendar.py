"""Kalendarz pracy firmy dla modułów „Ludzi w NEXUSIE”.

Dzień roboczy = poniedziałek–piątek, nie święto ustawowe (biblioteka
``holidays`` przez ``app/core/scheduling.py``) i nie dzień wolny firmy
(``company_days_off``). Compass trzymał święta w tabeli zasianej raz na lata
2026–2030 — brak roku oznaczał cicho, że 1 stycznia jest dniem roboczym.
Tu święta liczy biblioteka dla każdego roku.

``WorkCalendar`` jest czysty (bez bazy); ``load_calendar`` dociąga dni wolne
firmy z zakresu. To JEDYNY kalendarz modułów „Ludzi”: urlopy, „Mój miesiąc”
(``time_calendar`` składa z niego siatkę miesiąca), dostępność dla zastępstw
(``availability_local``), premie i odejścia liczą dni robocze tutaj.
"""

from __future__ import annotations

import calendar as _stdlib_calendar
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
from types import MappingProxyType
from typing import Literal

import holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import _polish_holidays
from app.models.hr_profile import CompanyDayOff

DayKind = Literal["work", "weekend", "holiday", "company"]

#: Bezpiecznik pętli „następny dzień roboczy” (najdłuższa przerwa to kilka dni).
_MAX_GAP_DAYS = 31


@lru_cache(maxsize=32)
def _holiday_names(year: int) -> Mapping[date, str]:
    # Niemutowalna kopia: współdzielony obiekt ``holidays`` dopopulowuje lata
    # leniwie i nie jest bezpieczny między wątkami (patrz ``scheduling.py``).
    return MappingProxyType(dict(holidays.Poland(years=year, language="pl").items()))


def holiday_name(day: date) -> str | None:
    return _holiday_names(day.year).get(day)


@dataclass(frozen=True)
class WorkCalendar:
    """Dni robocze firmy; ``company_days_off`` to dzień → nazwa."""

    company_days_off: dict[date, str] = field(default_factory=dict)

    def kind(self, day: date) -> DayKind:
        if day.weekday() >= 5:
            return "weekend"
        if day in _polish_holidays(day.year):
            return "holiday"
        if day in self.company_days_off:
            return "company"
        return "work"

    def is_working_day(self, day: date) -> bool:
        return self.kind(day) == "work"

    def day_name(self, day: date) -> str | None:
        """Nazwa święta albo dnia wolnego firmy (do podpowiedzi w kalendarzu)."""

        if day in self.company_days_off:
            return self.company_days_off[day]
        return holiday_name(day)

    def working_days(self, start: date, end: date) -> list[date]:
        return [day for day in iter_days(start, end) if self.is_working_day(day)]

    def next_working_day_after(self, day: date) -> date:
        """Pierwszy dzień roboczy po ``day`` (data powrotu w autoodpowiedzi)."""

        candidate = day + timedelta(days=1)
        for _ in range(_MAX_GAP_DAYS):
            if self.is_working_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        return candidate


def iter_days(start: date, end: date) -> list[date]:
    """Kolejne dni od ``start`` do ``end`` włącznie (pusto, gdy koniec przed startem)."""

    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def month_days(year: int, month: int) -> list[date]:
    last = _stdlib_calendar.monthrange(year, month)[1]
    return [date(year, month, number) for number in range(1, last + 1)]


def month_range(year: int, month: int) -> tuple[date, date]:
    """Pierwszy i ostatni dzień miesiąca."""

    return date(year, month, 1), date(
        year, month, _stdlib_calendar.monthrange(year, month)[1]
    )


def years_between(start: date, end: date) -> list[int]:
    return list(range(start.year, end.year + 1))


async def load_calendar(db: AsyncSession, start: date, end: date) -> WorkCalendar:
    """Kalendarz z dniami wolnymi firmy z zakresu (z zapasem na datę powrotu)."""

    rows = await db.execute(
        select(CompanyDayOff.day, CompanyDayOff.name).where(
            CompanyDayOff.day >= start,
            CompanyDayOff.day <= end + timedelta(days=_MAX_GAP_DAYS),
        )
    )
    return WorkCalendar(company_days_off={day: name for day, name in rows.all()})


def calendar_from_days(days: Iterable[tuple[date, str]]) -> WorkCalendar:
    return WorkCalendar(company_days_off=dict(days))
