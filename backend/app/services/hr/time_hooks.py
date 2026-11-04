"""Haki modułu urlopów na timesheet (wpina je moduł „leave” po decyzji).

* ``on_leave_approved`` — zatwierdzenie wniosku kasuje godziny pracy wpisane
  wcześniej na PEŁNE dni urlopu (także w zaakceptowanym timesheecie — wtedy
  z nową sumą kontrolną i śladem HR), a płatne dni B2B
  z puli dostają auto-wpis ``leave_paid``. Drugą połowę dnia wolno
  przepracować (jak w Compassie), ale najwyżej 4 h: ręczne wpisy dnia z połową
  urlopu skracamy od najpóźniej dodanego (decyzja Artura z 28.10.2026 —
  wpis 8 h sprzed wniosku dawał akceptującemu 12 h); nadgodzin nie ruszamy.
* ``on_leave_cancelled`` — anulowanie/odrzucenie zdejmuje auto-wpisy
  ``leave_paid`` z dni, których urlop już nie obejmuje.
* ``sent_months`` — miesiące dni z raportem godzin wysłanym albo przyjętym:
  zgłoszenie z B2B/zlecenia (bez niczyjej decyzji) ich nie przepisuje, tylko
  dostaje 409 (``leave_service``) — najpierw koordynator cofa raport do szkicu.

Zamknięty miesiąc płac (``payroll_locked``) i przyjęte potwierdzenie godzin
zlecenia po terminie wypłaty (``time_retention``, art. 8c) zostają nietknięte —
wynik niesie listę konfliktów do wyjaśnienia przez Płace. Funkcje nie commitują: wołający
zapisuje decyzję urlopu i zmianę godzin w jednej transakcji.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_time import Timesheet, TimesheetEntry

from app.services.hr import audit, people, time_retention
from app.services.hr.time_calendar import month_range
from app.services.hr.time_entries import (
    find_timesheet,
    leave_map,
    lock_timesheet,
    recompute_hash_if_set,
    remove_hours_on_full_leave_days,
    sync_leave_paid,
    trim_hours_on_half_leave_days,
)

logger = logging.getLogger(__name__)


def _by_month(days: Iterable[date]) -> dict[tuple[int, int], set[date]]:
    grouped: dict[tuple[int, int], set[date]] = defaultdict(set)
    for day in days:
        grouped[(day.year, day.month)].add(day)
    return grouped


#: Raport godzin, który leży u koordynatora albo jest przyjęty.
SENT_STATUSES: tuple[str, ...] = ("submitted", "approved")


async def sent_months(
    db: AsyncSession, user_id: int, days: Iterable[date], *, lock: bool
) -> list[tuple[str, str]]:
    """Miesiące dni (``RRRR-MM``, status), których raport godzin jest wysłany
    albo przyjęty.

    ``lock`` blokuje timesheety tych miesięcy (także szkice) do końca
    transakcji: wysyłka i akceptacja raportu czekają, aż zgłoszenie się zapisze
    albo odpadnie, więc nie przejdą między sprawdzeniem a hakiem godzin.
    """

    months = sorted(_by_month(days))
    if not months:
        return []
    statement = (
        select(Timesheet)
        .where(
            Timesheet.user_id == user_id,
            tuple_(Timesheet.year, Timesheet.month).in_(months),
        )
        .order_by(Timesheet.year, Timesheet.month)
    )
    if lock:
        statement = statement.with_for_update()
    return [
        (f"{row.year}-{row.month:02d}", row.status)
        for row in await db.scalars(statement)
        if row.status in SENT_STATUSES
    ]


def _retained(timesheet: Timesheet, employment_type: Optional[str]) -> bool:
    """Potwierdzenie godzin zlecenia po terminie wypłaty — godziny bez zmian
    (art. 8c, ``time_retention``); osoba dostaje ostrzeżenie jak przy
    zamkniętym miesiącu płac, Płace powiadomienie."""

    if not time_retention.sheet_frozen(timesheet, current_form=employment_type):
        return False
    logger.info(
        "[hr_time] potwierdzenie godzin w archiwum — bez zmian ts=%s", timesheet.id
    )
    return True


def _hours_text(value: Decimal) -> str:
    return format(value.normalize(), "f") if value else "0"


def _trimmed_days(
    trimmed: list[tuple[TimesheetEntry, Decimal, Decimal]],
) -> list[dict[str, str]]:
    """Dzień → suma skróconych wpisów przed i po (ślad dla Płac i koordynatora)."""

    totals: dict[date, list[Decimal]] = defaultdict(
        lambda: [Decimal("0"), Decimal("0")]
    )
    for entry, before, after in trimmed:
        totals[entry.work_date][0] += before
        totals[entry.work_date][1] += after
    return [
        {
            "day": day.isoformat(),
            "hours_before": _hours_text(before),
            "hours_after": _hours_text(after),
        }
        for day, (before, after) in sorted(totals.items())
    ]


async def on_leave_approved(
    db: AsyncSession, user_id: int, days: Iterable[date]
) -> dict[str, Any]:
    profile = await people.profile_of(db, user_id)
    employment_type = profile.employment_type if profile else None
    result: dict[str, Any] = {
        "removed_entries": 0,
        "trimmed_entries": 0,
        "timesheets_touched": 0,
        "locked_conflicts": [],
        "sent_changed": [],
    }
    for (year, month), month_days in sorted(_by_month(days).items()):
        found = await find_timesheet(db, user_id, year, month)
        if found is None:
            # Bez timesheetu nie ma czego uzgadniać: auto-wpisy zapisze pierwszy
            # zapis miesiąca (``open_draft``), a odczyt pokazuje je bez zapisu.
            continue
        timesheet = await lock_timesheet(db, found.id)
        if timesheet.payroll_locked or _retained(timesheet, employment_type):
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
        # Przed ``sync_leave_paid``: połowa puli B2B dostaje auto-wpis 4 h
        # tylko wtedy, gdy ręczne godziny dnia mieszczą się już w 4 h.
        trimmed = await trim_hours_on_half_leave_days(
            db,
            timesheet=timesheet,
            caps={
                day: leave.manual_cap
                for day in month_days
                if (leave := leaves.get(day)) is not None and not leave.leave.is_full
            },
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
        if trimmed:
            await recompute_hash_if_set(db, timesheet)
            audit.record(
                db,
                actor_user_id=None,
                subject_user_id=user_id,
                entity_type="timesheet",
                entity_id=timesheet.id,
                action="leave_hours_trimmed",
                details={
                    "status": timesheet.status,
                    "days": _trimmed_days(trimmed),
                    "entries": len(trimmed),
                    "removed": sum(1 for _, _, after in trimmed if after <= 0),
                },
            )
        if removed or trimmed or changed:
            result["timesheets_touched"] += 1
            if timesheet.status in SENT_STATUSES:
                result["sent_changed"].append(f"{year}-{month:02d}")
        result["removed_entries"] += len(removed)
        result["trimmed_entries"] += len(trimmed)
    return result


async def on_leave_cancelled(
    db: AsyncSession, user_id: int, days: Iterable[date]
) -> dict[str, Any]:
    profile = await people.profile_of(db, user_id)
    employment_type = profile.employment_type if profile else None
    result: dict[str, Any] = {
        "timesheets_touched": 0,
        "locked_conflicts": [],
        "sent_changed": [],
    }
    for year, month in sorted(_by_month(days)):
        found = await find_timesheet(db, user_id, year, month)
        if found is None:
            continue
        timesheet = await lock_timesheet(db, found.id)
        if timesheet.payroll_locked or _retained(timesheet, employment_type):
            result["locked_conflicts"].append(f"{year}-{month:02d}")
            continue
        if await sync_leave_paid(
            db, timesheet=timesheet, employment_type=employment_type
        ):
            result["timesheets_touched"] += 1
            if timesheet.status in SENT_STATUSES:
                result["sent_changed"].append(f"{year}-{month:02d}")
    return result
