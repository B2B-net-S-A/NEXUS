"""Most Płac do timesheetów („Mój miesiąc”, moduł ``time``).

JEDYNE miejsce, w którym Płace czytają ``timesheets`` / ``timesheet_entries``
i ustawiają ``payroll_locked``. Surowy SQL, bez modeli modułu czasu — Płace
nie zależą od jego warstwy ORM, a zmiana kształtu tabel psuje jeden plik.

Naprawa błędu Compassa: raport płacowy sumował godziny z KAŻDEGO statusu
timesheetu, także szkicu (``internal-payroll.ts:76-103``). Tu liczą się
wyłącznie timesheety zatwierdzone (``status = 'approved'``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr_time_schema import STANDARD_DAY_HOURS

APPROVED = "approved"


@dataclass(frozen=True)
class ApprovedHours:
    hours: Decimal
    overtime_hours: Decimal


async def approved_hours(
    db: AsyncSession, year: int, month: int
) -> dict[int, ApprovedHours]:
    """Godziny z zatwierdzonych timesheetów miesiąca, per osoba.

    Nadgodziny = suma po dniach ``max(suma_dnia − 8 h, 0)`` — tak liczy widok
    miesiąca i kolejka akceptacji modułu czasu. Flaga ``is_overtime`` wpisu
    oznacza wpis, który przepycha dzień ponad normę, nie liczbę nadgodzin
    (5 h + 5 h jednego dnia = 2 h nadgodzin, nie 5 h).
    """

    rows = await db.execute(
        text(
            "SELECT user_id, COALESCE(SUM(day_hours), 0) AS hours, "
            "COALESCE(SUM(GREATEST(day_hours - :standard, 0)), 0) AS overtime "
            "FROM ("
            "  SELECT t.user_id, e.work_date, SUM(e.hours) AS day_hours "
            "  FROM timesheets t "
            "  JOIN timesheet_entries e ON e.timesheet_id = t.id "
            "  WHERE t.year = :year AND t.month = :month AND t.status = :approved "
            "  GROUP BY t.user_id, e.work_date"
            ") days GROUP BY user_id"
        ),
        {
            "year": year,
            "month": month,
            "approved": APPROVED,
            "standard": STANDARD_DAY_HOURS,
        },
    )
    return {
        int(row.user_id): ApprovedHours(
            hours=Decimal(row.hours), overtime_hours=Decimal(row.overtime)
        )
        for row in rows
    }


async def timesheet_statuses(db: AsyncSession, year: int, month: int) -> dict[int, str]:
    """Status timesheetu miesiąca per osoba (brak klucza = brak timesheetu)."""

    rows = await db.execute(
        text(
            "SELECT user_id, status FROM timesheets "
            "WHERE year = :year AND month = :month"
        ),
        {"year": year, "month": month},
    )
    return {int(row.user_id): str(row.status) for row in rows}


async def set_payroll_lock(
    db: AsyncSession, year: int, month: int, user_ids: Iterable[int], *, locked: bool
) -> int:
    """Zamknięcie (``locked=True``) albo otwarcie miesiąca płac na timesheetach osób.

    Dotyczy tylko osób z listy płac tego miesiąca — timesheet obcej osoby
    zostaje nietknięty. Zwraca liczbę zmienionych timesheetów.
    """

    ids = sorted(set(user_ids))
    if not ids:
        return 0
    result = await db.execute(
        text(
            "UPDATE timesheets SET payroll_locked = :locked, updated_at = now() "
            "WHERE year = :year AND month = :month "
            "AND user_id = ANY(:ids) AND payroll_locked IS DISTINCT FROM :locked"
        ),
        {"locked": locked, "year": year, "month": month, "ids": ids},
    )
    return int(result.rowcount or 0)


async def locked_user_ids(db: AsyncSession, year: int, month: int) -> set[int]:
    rows = await db.execute(
        text(
            "SELECT user_id FROM timesheets "
            "WHERE year = :year AND month = :month AND payroll_locked"
        ),
        {"year": year, "month": month},
    )
    return {int(row.user_id) for row in rows}


__all__ = [
    "ApprovedHours",
    "approved_hours",
    "locked_user_ids",
    "set_payroll_lock",
    "timesheet_statuses",
]
