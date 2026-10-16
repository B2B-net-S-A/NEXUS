"""Haki modułu urlopów na timesheet (wpina je moduł „leave” po decyzji).

* ``on_leave_approved`` — zatwierdzenie wniosku kasuje godziny pracy wpisane
  wcześniej na PEŁNE dni urlopu (także w zaakceptowanym timesheecie — wtedy
  z nową sumą kontrolną i śladem HR), a dni płatnego urlopu B2B/zlecenia
  z puli dostają auto-wpis ``leave_paid``. Połówek dnia nie ruszamy: drugą
  połowę wolno przepracować (jak w Compassie).
* ``on_leave_cancelled`` — anulowanie/odrzucenie zdejmuje auto-wpisy
  ``leave_paid`` z dni, których urlop już nie obejmuje.

Zamknięty miesiąc płac (``payroll_locked``) zostaje nietknięty — wynik niesie
listę konfliktów do wyjaśnienia przez Płace. Funkcje nie commitują: wołający
zapisuje decyzję urlopu i zmianę godzin w jednej transakcji.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.hr import audit, people
from app.services.hr.time_calendar import month_range
from app.services.hr.time_entries import (
    find_timesheet,
    leave_map,
    lock_timesheet,
    recompute_hash_if_set,
    remove_hours_on_full_leave_days,
    sync_leave_paid,
)


def _by_month(days: Iterable[date]) -> dict[tuple[int, int], set[date]]:
    grouped: dict[tuple[int, int], set[date]] = defaultdict(set)
    for day in days:
        grouped[(day.year, day.month)].add(day)
    return grouped


async def on_leave_approved(
    db: AsyncSession, user_id: int, days: Iterable[date]
) -> dict[str, Any]:
    profile = await people.profile_of(db, user_id)
    employment_type = profile.employment_type if profile else None
    result: dict[str, Any] = {
        "removed_entries": 0,
        "timesheets_touched": 0,
        "locked_conflicts": [],
    }
    for (year, month), month_days in sorted(_by_month(days).items()):
        found = await find_timesheet(db, user_id, year, month)
        if found is None:
            continue  # auto-wpisy powstaną przy pierwszym otwarciu miesiąca
        timesheet = await lock_timesheet(db, found.id)
        if timesheet.payroll_locked:
            result["locked_conflicts"].append(f"{year}-{month:02d}")
            continue
        start, end = month_range(year, month)
        leaves = await leave_map(
            db, user_id=user_id, employment_type=employment_type, start=start, end=end
        )
        full_days = {
            day
            for day in month_days
            if (leave := leaves.get(day)) is not None and leave.leave.is_full
        }
        removed = await remove_hours_on_full_leave_days(
            db, timesheet=timesheet, days=full_days
        )
        changed = await sync_leave_paid(
            db, timesheet=timesheet, employment_type=employment_type
        )
        if removed:
            await db.flush()
            await recompute_hash_if_set(db, timesheet)
            audit.record(
                db,
                actor_user_id=None,
                subject_user_id=user_id,
                entity_type="timesheet",
                entity_id=timesheet.id,
                action="leave_hours_removed",
                details={
                    "status": timesheet.status,
                    "days": sorted({row.work_date.isoformat() for row in removed}),
                    "entries": len(removed),
                },
            )
        if removed or changed:
            result["timesheets_touched"] += 1
        result["removed_entries"] += len(removed)
    return result


async def on_leave_cancelled(
    db: AsyncSession, user_id: int, days: Iterable[date]
) -> dict[str, Any]:
    profile = await people.profile_of(db, user_id)
    employment_type = profile.employment_type if profile else None
    result: dict[str, Any] = {"timesheets_touched": 0, "locked_conflicts": []}
    for year, month in sorted(_by_month(days)):
        found = await find_timesheet(db, user_id, year, month)
        if found is None:
            continue
        timesheet = await lock_timesheet(db, found.id)
        if timesheet.payroll_locked:
            result["locked_conflicts"].append(f"{year}-{month:02d}")
            continue
        if await sync_leave_paid(
            db, timesheet=timesheet, employment_type=employment_type
        ):
            result["timesheets_touched"] += 1
    return result
