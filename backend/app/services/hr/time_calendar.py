"""Siatka miesiąca dla „Mojego miesiąca”: weekendy, święta, dni wolne firmy.

Dni robocze, święta i dni wolne firmy liczy jeden kalendarz modułu
(``app/services/hr/calendar.py``: ``WorkCalendar`` + ``load_calendar``) —
tu jest tylko układ dnia dla siatki i termin wysłania timesheetu.
"Dziś" i bieżący miesiąc zawsze z kalendarza firmy (``business_today``).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr.calendar import (
    holiday_name,
    load_calendar,
    month_days,
    month_range,
)

#: Termin wysłania timesheetu: 5. dzień miesiąca po rozliczanym (Compass).
DEADLINE_DAY = 5


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
    #: Z ``WorkCalendar.is_working_day`` — jedna reguła dnia roboczego.
    is_working_day: bool

    @property
    def is_weekend(self) -> bool:
        return self.day.weekday() >= 5


async def month_calendar(db: AsyncSession, year: int, month: int) -> list[CalendarDay]:
    start, end = month_range(year, month)
    calendar = await load_calendar(db, start, end)
    return [
        CalendarDay(
            day=day,
            holiday=holiday_name(day),
            day_off=calendar.company_days_off.get(day),
            is_working_day=calendar.is_working_day(day),
        )
        for day in month_days(year, month)
    ]


__all__ = [
    "DEADLINE_DAY",
    "CalendarDay",
    "holiday_name",
    "month_calendar",
    "month_days",
    "month_range",
    "previous_month",
    "submission_deadline",
]
