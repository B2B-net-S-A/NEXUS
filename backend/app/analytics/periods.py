"""Canonical analytics periods in the Europe/Warsaw business timezone."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status


WARSAW = ZoneInfo("Europe/Warsaw")
MAX_CUSTOM_PERIOD_DAYS = 366


class AnalyticsPeriodKind(str, Enum):
    day = "day"
    week = "week"
    month = "month"
    quarter = "quarter"
    year = "year"
    custom = "custom"


@dataclass(frozen=True)
class AnalyticsPeriod:
    """A timezone-aware, half-open reporting interval ``[start, end)``."""

    kind: AnalyticsPeriodKind
    start: datetime
    end: datetime
    timezone: str = "Europe/Warsaw"


def _midnight(value: date) -> datetime:
    return datetime.combine(value, time.min, tzinfo=WARSAW)


def _next_month(year: int, month: int) -> tuple[int, int]:
    if month == 12:
        return year + 1, 1
    return year, month + 1


def resolve_period(
    kind: AnalyticsPeriodKind,
    *,
    now: datetime | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> AnalyticsPeriod:
    """Resolve a requested period using Warsaw calendar boundaries.

    Custom ``to`` is the exclusive boundary.  This is intentionally strict:
    ``from=2026-07-01&to=2026-08-01`` means the whole of July and avoids hidden
    ``23:59:59.999999`` conversions.
    """

    current = now or datetime.now(WARSAW)
    if current.tzinfo is None:
        current = current.replace(tzinfo=WARSAW)
    else:
        current = current.astimezone(WARSAW)

    if kind is AnalyticsPeriodKind.custom:
        if date_from is None or date_to is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Custom period requires both 'from' and 'to' dates",
            )
        start = _midnight(date_from)
        end = _midnight(date_to)
        if end <= start:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Custom period 'to' must be later than 'from'",
            )
        if (date_to - date_from).days > MAX_CUSTOM_PERIOD_DAYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Custom period cannot exceed {MAX_CUSTOM_PERIOD_DAYS} days",
            )
        return AnalyticsPeriod(kind=kind, start=start, end=end)

    if date_from is not None or date_to is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="'from' and 'to' are only valid with period=custom",
        )

    today = current.date()
    if kind is AnalyticsPeriodKind.day:
        start_date = today
        end_date = today + timedelta(days=1)
    elif kind is AnalyticsPeriodKind.week:
        start_date = today - timedelta(days=today.weekday())
        end_date = start_date + timedelta(days=7)
    elif kind is AnalyticsPeriodKind.month:
        start_date = today.replace(day=1)
        end_year, end_month = _next_month(start_date.year, start_date.month)
        end_date = date(end_year, end_month, 1)
    elif kind is AnalyticsPeriodKind.quarter:
        start_month = ((today.month - 1) // 3) * 3 + 1
        start_date = date(today.year, start_month, 1)
        end_year = today.year + (1 if start_month == 10 else 0)
        end_month = 1 if start_month == 10 else start_month + 3
        end_date = date(end_year, end_month, 1)
    elif kind is AnalyticsPeriodKind.year:
        start_date = date(today.year, 1, 1)
        end_date = date(today.year + 1, 1, 1)
    else:  # pragma: no cover - Enum makes this unreachable
        raise ValueError(f"Unsupported period kind: {kind}")

    return AnalyticsPeriod(
        kind=kind, start=_midnight(start_date), end=_midnight(end_date)
    )
