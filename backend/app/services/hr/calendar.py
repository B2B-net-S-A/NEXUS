"""Kalendarz pracy firmy dla modułów „Ludzi w NEXUSIE”.

Dzień roboczy = poniedziałek–piątek, nie święto ustawowe (biblioteka
``holidays`` przez ``app/core/scheduling.py``) i nie dzień wolny firmy
(``company_days_off``). Compass trzymał święta w tabeli zasianej raz na lata
2026–2030 — brak roku oznaczał cicho, że 1 stycznia jest dniem roboczym.
Tu święta liczy biblioteka dla każdego roku.

``WorkCalendar`` jest czysty (bez bazy); ``load_calendar`` dociąga dni wolne
firmy z zakresu.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import lru_cache
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
def _holiday_names(year: int) -> dict[date, str]:
    return dict(holidays.Poland(years=year, language="pl").items())


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
        if end < start:
            return []
        span = (end - start).days + 1
        days = (start + timedelta(days=offset) for offset in range(span))
        return [day for day in days if self.is_working_day(day)]

    def next_working_day_after(self, day: date) -> date:
        """Pierwszy dzień roboczy po ``day`` (data powrotu w autoodpowiedzi)."""

        candidate = day + timedelta(days=1)
        for _ in range(_MAX_GAP_DAYS):
            if self.is_working_day(candidate):
                return candidate
            candidate += timedelta(days=1)
        return candidate


def month_days(year: int, month: int) -> list[date]:
    first = date(year, month, 1)
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return [first + timedelta(days=offset) for offset in range((nxt - first).days)]


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
