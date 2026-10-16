"""Kalendarz miesiąca dla „Mojego miesiąca”: weekendy, święta, dni wolne firmy.

Święta ustawowe liczy biblioteka ``holidays`` (to samo źródło co
``app/core/scheduling.py``); dni wolne firmy są w ``company_days_off``
(Kadry). Dzień roboczy = pon–pt, nie święto i nie dzień wolny firmy.
"Dziś" i bieżący miesiąc zawsze z kalendarza firmy (``business_today``).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from types import MappingProxyType
from typing import Mapping, Optional

import holidays
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import CompanyDayOff

#: Termin wysłania timesheetu: 5. dzień miesiąca po rozliczanym (Compass).
DEADLINE_DAY = 5


@lru_cache(maxsize=32)
def _holiday_names(year: int) -> Mapping[date, str]:
    # Niemutowalna kopia: współdzielony obiekt ``holidays`` dopopulowuje lata
    # leniwie i nie jest bezpieczny między wątkami (patrz ``scheduling.py``).
    return MappingProxyType(dict(holidays.Poland(years=year).items()))


def holiday_name(day: date) -> Optional[str]:
    return _holiday_names(day.year).get(day)


def month_days(year: int, month: int) -> list[date]:
    last = calendar.monthrange(year, month)[1]
    return [date(year, month, number) for number in range(1, last + 1)]


def month_range(year: int, month: int) -> tuple[date, date]:
    days = month_days(year, month)
    return days[0], days[-1]


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def submission_deadline(year: int, month: int) -> date:
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(next_year, next_month, DEADLINE_DAY)


@dataclass(frozen=True)
class CalendarDay:
    day: date
    holiday: Optional[str]
    day_off: Optional[str]

    @property
    def is_weekend(self) -> bool:
        return self.day.weekday() >= 5

    @property
    def is_working_day(self) -> bool:
        return not self.is_weekend and self.holiday is None and self.day_off is None


async def company_days_off(db: AsyncSession, start: date, end: date) -> dict[date, str]:
    rows = await db.execute(
        select(CompanyDayOff.day, CompanyDayOff.name).where(
            CompanyDayOff.day >= start, CompanyDayOff.day <= end
        )
    )
    return {day: name for day, name in rows.all()}


async def month_calendar(db: AsyncSession, year: int, month: int) -> list[CalendarDay]:
    start, end = month_range(year, month)
    days_off = await company_days_off(db, start, end)
    return [
        CalendarDay(day=day, holiday=holiday_name(day), day_off=days_off.get(day))
        for day in month_days(year, month)
    ]


def iter_days(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]
