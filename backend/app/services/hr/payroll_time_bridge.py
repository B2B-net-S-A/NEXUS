"""Most Płac do timesheetów („Mój miesiąc”, moduł ``time``).

JEDYNE miejsce, w którym Płace czytają ``timesheets`` / ``timesheet_entries``
i ustawiają ``payroll_locked``. Surowy SQL, bez modeli modułu czasu — Płace
nie zależą od jego warstwy ORM, a zmiana kształtu tabel psuje jeden plik.

Naprawa błędu Compassa: raport płacowy sumował godziny z KAŻDEGO statusu
timesheetu, także szkicu (``internal-payroll.ts:76-103``). Tu liczą się
wyłącznie timesheety zatwierdzone (``status = 'approved'``).

Nadgodziny liczą się jak w „Moim miesiącu” (``time_month``): dzień urlopu
zajmuje swoją część normy (pół dnia = 4 h), chyba że to płatny urlop
kontraktora z auto-wpisem ``leave_paid`` — ten jest już wśród wpisów.
Urlop czytamy z kolumn kontraktu modułu urlopów (jak ``time_leave_bridge``).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr.payroll_periods import month_end, month_start
from app.services.hr.time_leave_bridge import CONTRACTOR_TYPES, POOL_LEAVE_TYPES
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

    Nadgodziny = suma po dniach ``max(suma_dnia + urlop_dnia − 8 h, 0)`` — tak
    liczy widok miesiąca (``time_month``). ``urlop_dnia`` to 8 h × ułamek dnia
    aktywnego urlopu (pół dnia = 4 h), 0 dla płatnego urlopu kontraktora
    z auto-wpisem. Flaga ``is_overtime`` wpisu oznacza wpis, który przepycha
    dzień ponad normę, nie liczbę nadgodzin (5 h + 5 h jednego dnia = 2 h
    nadgodzin, nie 5 h).
    """

    rows = await db.execute(
        text(
            "SELECT user_id, COALESCE(SUM(day_hours), 0) AS hours, "
            "COALESCE(SUM(GREATEST(day_hours + occupied - :standard, 0)), 0) "
            "AS overtime "
            "FROM ("
            "  SELECT t.user_id, e.work_date, SUM(e.hours) AS day_hours, "
            "         COALESCE(MAX(o.occupied), 0) AS occupied "
            "  FROM timesheets t "
            "  JOIN timesheet_entries e ON e.timesheet_id = t.id "
            "  LEFT JOIN ("
            "    SELECT d.user_id, d.day, "
            "           MAX(CAST(:standard AS numeric) * LEAST(d.fraction, 1)) "
            "           AS occupied "
            "    FROM leave_request_days d "
            "    JOIN leave_requests r ON r.id = d.leave_request_id "
            "    LEFT JOIN employee_profiles p ON p.user_id = d.user_id "
            "    WHERE d.active AND r.status IN ('pending', 'approved') "
            "      AND d.day BETWEEN :first AND :last "
            "      AND NOT (r.status = 'approved' AND d.paid "
            "               AND r.leave_type = ANY(:pool_types) "
            "               AND COALESCE(p.employment_type, '') = ANY(:contractors)) "
            "    GROUP BY d.user_id, d.day"
            "  ) o ON o.user_id = t.user_id AND o.day = e.work_date "
            "  WHERE t.year = :year AND t.month = :month AND t.status = :approved "
            "  GROUP BY t.user_id, e.work_date"
            ") days GROUP BY user_id"
        ),
        {
            "year": year,
            "month": month,
            "approved": APPROVED,
            "standard": STANDARD_DAY_HOURS,
            "first": month_start(year, month),
            "last": month_end(year, month),
            "pool_types": sorted(POOL_LEAVE_TYPES),
            "contractors": sorted(CONTRACTOR_TYPES),
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


async def lock_month_timesheets(db: AsyncSession, year: int, month: int) -> int:
    """Blokada wszystkich timesheetów miesiąca (``FOR UPDATE``, po id).

    Zamknięcie bierze ją PRZED liczeniem raportu: akceptacja albo zmiana
    godzin w toku kończy się wcześniej (i raport ją widzi), a późniejsza
    czeka i trafia na ``payroll_locked``.
    """

    rows = await db.execute(
        text(
            "SELECT id FROM timesheets WHERE year = :year AND month = :month "
            "ORDER BY id FOR UPDATE"
        ),
        {"year": year, "month": month},
    )
    return len(rows.all())


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
    "lock_month_timesheets",
    "locked_user_ids",
    "set_payroll_lock",
    "timesheet_statuses",
]
