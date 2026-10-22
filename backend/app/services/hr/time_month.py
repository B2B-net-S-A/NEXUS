"""Siatka „Mojego miesiąca” i kolejka akceptacji zespołu.

Jeden wiersz na dzień: miejsce pracy (domyślne z kartoteki albo wyjątek),
urlop z mostu (tylko do odczytu), święto/dzień wolny, wpisy i suma godzin.
Rodzaj nieobecności widzi wyłącznie osoba, jej przełożony i Kadry (D6) —
reszta dostaje „Nieobecność”.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import AttendanceDay, Timesheet, TimesheetEntry
from app.models.user import User
from app.services.hr import audit
from app.services.hr import time_leave_bridge as bridge
from app.services.hr.leave_policy import type_label
from app.services.hr.recipients import supervisor_of
from app.services.hr.time_access import Actor
from app.services.hr.time_calendar import (
    month_calendar,
    month_range,
    submission_deadline,
)
from app.services.hr.time_entries import (
    STANDARD,
    DayLeave,
    TimeError,
    entries_of,
    entry_payload,
    employed_on,
    find_timesheet,
    leave_map,
    planned_leave_paid,
)
from app.services.hr_foundation_schema import WORKING_STATUSES
from app.services.hr_time_schema import ATTENDANCE_STATUSES, LOCATIONS

NEUTRAL_ABSENCE = "Nieobecność"
MAX_NOTE = 500

#: Statusy zatrudnienia (``employee_profiles.employment_status``), w których
#: osoba prowadzi timesheet — przed startem (``pending``) i po odejściu nie.
TIMESHEET_EMPLOYMENT_STATUSES = WORKING_STATUSES


def _leave_payload(
    day_leave: DayLeave, *, show_type: bool, employment_type: Optional[str] = None
) -> dict[str, Any]:
    leave = day_leave.leave
    # Słowa formy (D4): na B2B dzień z puli to „Przerwa w świadczeniu usług”.
    label = type_label(leave.leave_type, employment_type)
    return {
        "status": leave.status,
        "fraction": float(leave.fraction),
        "full": leave.is_full,
        "paid_work": day_leave.paid_work,
        "paid_hours": float(day_leave.paid_hours),
        "label": label if show_type else NEUTRAL_ABSENCE,
    }


def timesheet_payload(
    timesheet: Optional[Timesheet], *, approver_name: Optional[str] = None
) -> Optional[dict[str, Any]]:
    if timesheet is None:
        return None
    return {
        "id": timesheet.id,
        "status": timesheet.status,
        "submitted_at": timesheet.submitted_at,
        "return_note": timesheet.return_note,
        "returned_at": timesheet.returned_at,
        "approved_at": timesheet.approved_at,
        "approved_by_name": approver_name,
        "payroll_locked": timesheet.payroll_locked,
        "pdf_hash": timesheet.pdf_hash,
    }


async def _name_of(db: AsyncSession, user_id: Optional[int]) -> Optional[str]:
    if user_id is None:
        return None
    return await db.scalar(select(User.name).where(User.id == user_id))


async def month_view(
    db: AsyncSession,
    *,
    subject_user: User,
    subject: EmployeeProfile,
    year: int,
    month: int,
    show_leave_type: bool,
) -> dict[str, Any]:
    """Widok miesiąca — sam odczyt, bez zapisu.

    Szkic (także „wirtualny”, gdy wiersza timesheetu jeszcze nie ma) pokazuje
    auto-wpisy płatnej puli kontraktora tak, jak zapisze je pierwszy zapis
    miesiąca (``time_entries.open_draft``): ta sama reguła
    ``planned_leave_paid``. Wysłany, zaakceptowany albo zamknięty w płacach
    timesheet pokazuje zapisane wpisy. Do 17.10.2026 sam odczyt zakładał
    timesheet i auto-wpisy (kształt z Compassa).
    """

    timesheet = await find_timesheet(db, subject_user.id, year, month)
    start, end = month_range(year, month)
    leaves = await leave_map(
        db,
        user_id=subject_user.id,
        employment_type=subject.employment_type,
        start=start,
        end=end,
    )
    calendar = await month_calendar(db, year, month)
    exceptions = {
        row.day: row
        for row in await db.scalars(
            select(AttendanceDay).where(
                AttendanceDay.user_id == subject_user.id,
                AttendanceDay.day >= start,
                AttendanceDay.day <= end,
            )
        )
    }
    entries = await entries_of(db, timesheet.id) if timesheet else []
    by_day: dict[date, list] = defaultdict(list)
    for entry in entries:
        by_day[entry.work_date].append(entry)
    draft = timesheet is None or (
        timesheet.status == "draft" and not timesheet.payroll_locked
    )
    planned = planned_leave_paid(leaves, entries) if draft else None

    days: list[dict[str, Any]] = []
    totals = {
        "work_hours": Decimal("0"),
        "leave_paid_hours": Decimal("0"),
        "overtime_hours": Decimal("0"),
        "leave_days": Decimal("0"),
        "working_days": 0,
        "days_missing": 0,
    }
    for item in calendar:
        day_leave = leaves.get(item.day)
        day_entries = by_day.get(item.day, [])
        manual_entries = [e for e in day_entries if e.source != "leave_paid"]
        manual = sum((Decimal(e.hours) for e in manual_entries), Decimal("0"))
        if planned is None:
            auto = sum(
                (Decimal(e.hours) for e in day_entries if e.source == "leave_paid"),
                Decimal("0"),
            )
        else:
            # Szkic: auto-wpis, jaki zapisze pierwszy zapis (zapisany zostaje
            # na liście, gdy się zgadza — jak w ``sync_leave_paid``).
            auto = planned.get(item.day, Decimal("0"))
            kept = next(
                (
                    e
                    for e in day_entries
                    if e.source == "leave_paid" and Decimal(e.hours) == auto
                ),
                None,
            )
            day_entries = [
                e for e in day_entries if e.source != "leave_paid" or e is kept
            ]
        occupied = day_leave.occupied_hours if day_leave else Decimal("0")
        excess = max(Decimal("0"), manual + auto + occupied - STANDARD)
        exception = exceptions.get(item.day)
        full_leave = day_leave is not None and day_leave.leave.is_full
        if exception is not None:
            location, source = exception.location, "exception"
        elif item.is_working_day and not full_leave:
            location, source = subject.default_location, "default"
        else:
            location, source = None, None
        if item.is_working_day:
            totals["working_days"] += 1
            if day_leave is not None:
                totals["leave_days"] += day_leave.leave.fraction
            if (
                not day_entries
                and not auto
                and not full_leave
                and employed_on(subject, item.day)
            ):
                totals["days_missing"] += 1
        totals["work_hours"] += manual
        totals["leave_paid_hours"] += auto
        totals["overtime_hours"] += excess
        days.append(
            {
                "date": item.day.isoformat(),
                "weekday": item.day.isoweekday(),
                "is_weekend": item.is_weekend,
                "holiday": item.holiday,
                "day_off": item.day_off,
                "working_day": item.is_working_day,
                "location": location,
                "location_source": source,
                "attendance_status": exception.status if exception else None,
                "attendance_note": exception.note if exception else None,
                "leave": _leave_payload(
                    day_leave,
                    show_type=show_leave_type,
                    employment_type=subject.employment_type,
                )
                if day_leave
                else None,
                "entries": [entry_payload(e) for e in day_entries],
                "hours": float(manual + auto),
                "capacity": None
                if day_leave is not None and day_leave.blocks_day
                else float(STANDARD - occupied),
                "overtime_hours": float(excess),
            }
        )
    approver_name = await _name_of(db, timesheet.approved_by if timesheet else None)
    # Kto akceptuje — ta sama reguła, która kieruje do niego timesheet
    # (``recipients.supervisor_of``); ``None`` = Kadry (front pisze „Kadry”).
    supervisor = await supervisor_of(db, subject)
    deadline = submission_deadline(year, month)
    return {
        "user_id": subject_user.id,
        "name": subject_user.name,
        "year": year,
        "month": month,
        "deadline": deadline.isoformat(),
        "employment_type": subject.employment_type,
        "default_location": subject.default_location,
        "can_log_overtime": subject.can_log_overtime,
        "approver_name": None
        if supervisor.kind == "people_admin"
        else supervisor.label,
        "timesheet": timesheet_payload(timesheet, approver_name=approver_name),
        "days": days,
        "totals": {
            "work_hours": float(totals["work_hours"]),
            "leave_paid_hours": float(totals["leave_paid_hours"]),
            "overtime_hours": float(totals["overtime_hours"]),
            "leave_days": float(totals["leave_days"]),
            "working_days": totals["working_days"],
            "norm_hours": totals["working_days"] * int(STANDARD),
            "days_missing": totals["days_missing"],
        },
    }


# ── Obecność (wyjątki) ────────────────────────────────────────────────────────


async def set_attendance(
    db: AsyncSession,
    *,
    subject: EmployeeProfile,
    actor_user_id: int,
    day: date,
    status: str,
    location: Optional[str],
    note: Optional[str],
) -> dict[str, Any]:
    if status not in ATTENDANCE_STATUSES:
        raise TimeError("Nieznany status dnia.")
    if status == "active":
        if location not in LOCATIONS:
            raise TimeError("Wybierz biuro albo pracę zdalną.")
    else:
        location = None
    text = (note or "").strip() or None
    if text and len(text) > MAX_NOTE:
        raise TimeError(f"Notatka może mieć najwyżej {MAX_NOTE} znaków.")
    leave = await bridge.leave_days(db, [subject.user_id], day, day)
    if any(item.is_full for item in leave):
        raise TimeError(
            "W dniu urlopu nie ustawia się miejsca pracy — zmień wniosek urlopowy."
        )
    existing = await db.scalar(
        select(AttendanceDay).where(
            AttendanceDay.user_id == subject.user_id, AttendanceDay.day == day
        )
    )
    back_to_default = (
        status == "active" and location == subject.default_location and text is None
    )
    if back_to_default:
        if existing is not None:
            await db.delete(existing)
        result = {"location": location, "source": "default", "status": status}
    else:
        if existing is None:
            existing = AttendanceDay(user_id=subject.user_id, day=day)
            db.add(existing)
        existing.status = status
        existing.location = location
        existing.note = text
        existing.created_by = actor_user_id
        result = {"location": location, "source": "exception", "status": status}
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor_user_id,
        subject_user_id=subject.user_id,
        entity_type="attendance_day",
        entity_id=day.isoformat(),
        action="attendance_set",
        details={"status": status, "location": location},
    )
    return {"date": day.isoformat(), **result}


# ── Kolejka akceptacji ────────────────────────────────────────────────────────


def _employed_in(profile: EmployeeProfile, start: date, end: date) -> bool:
    if profile.work_start_date and profile.work_start_date > end:
        return False
    if profile.last_working_day and profile.last_working_day < start:
        return False
    return True


async def month_norm_hours(db: AsyncSession, year: int, month: int) -> int:
    """Norma miesiąca (dni robocze kalendarza firmy × 8 h) — jak „Mój miesiąc”."""

    calendar = await month_calendar(db, year, month)
    return sum(1 for item in calendar if item.is_working_day) * int(STANDARD)


async def team_queue(
    db: AsyncSession,
    *,
    actor: Actor,
    year: int,
    month: int,
    missing_before: Optional[date] = None,
) -> list[dict[str, Any]]:
    """Zespół akceptującego na miesiąc; brak timesheetu = wiersz-zaślepka.

    ``missing_before`` (Mój zespół, 22.10.2026): dla szkicu i braku raportu
    dopisuje ``missing_dates`` — dni robocze przed tą datą bez wpisu i bez
    całodniowej nieobecności, ta sama reguła co ``days_missing`` w miesiącu
    osoby. Dzisiejszy dzień się nie liczy (rano nikt go jeszcze nie wpisał).
    """

    start, end = month_range(year, month)
    scope = select(EmployeeProfile, User).join(User, User.id == EmployeeProfile.user_id)
    if not actor.approves_everyone:
        scope = scope.where(
            or_(
                EmployeeProfile.manager_user_id == actor.user_id,
                EmployeeProfile.user_id.in_(
                    sorted(actor.covered_ids | actor.charges) or [-1]
                ),
            )
        )
    scope = scope.where(EmployeeProfile.user_id != actor.user_id)
    pairs = (await db.execute(scope)).all()
    timesheets = {
        row.user_id: row
        for row in await db.scalars(
            select(Timesheet).where(
                Timesheet.year == year,
                Timesheet.month == month,
                Timesheet.user_id.in_(
                    [profile.user_id for profile, _ in pairs] or [-1]
                ),
            )
        )
    }
    roster = [
        (profile, user)
        for profile, user in pairs
        if profile.user_id in timesheets
        or (
            profile.timesheet_required
            and profile.employment_status in TIMESHEET_EMPLOYMENT_STATUSES
            and user.is_active
            and _employed_in(profile, start, end)
        )
    ]
    sums: dict[tuple[int, date], Decimal] = {}
    if timesheets:
        rows = await db.execute(
            select(
                TimesheetEntry.timesheet_id,
                TimesheetEntry.work_date,
                func.sum(TimesheetEntry.hours),
            )
            .where(TimesheetEntry.timesheet_id.in_([t.id for t in timesheets.values()]))
            .group_by(TimesheetEntry.timesheet_id, TimesheetEntry.work_date)
        )
        sums = {(ts_id, day): Decimal(total) for ts_id, day, total in rows.all()}
    leaves = await bridge.leave_days(db, [p.user_id for p, _ in roster], start, end)
    leave_by_user: dict[int, dict[date, bridge.LeaveDay]] = defaultdict(dict)
    for item in leaves:
        leave_by_user[item.user_id][item.day] = item
    past_working_days = (
        [
            item.day
            for item in await month_calendar(db, year, month)
            if item.is_working_day and item.day < missing_before
        ]
        if missing_before is not None
        else []
    )

    items: list[dict[str, Any]] = []
    for profile, user in roster:
        timesheet = timesheets.get(profile.user_id)
        user_leaves = leave_by_user.get(profile.user_id, {})
        hours = overtime = Decimal("0")
        if timesheet is not None:
            for (ts_id, day), total in sums.items():
                if ts_id != timesheet.id:
                    continue
                hours += total
                leave = user_leaves.get(day)
                occupied = (
                    Decimal("0")
                    if leave is None or leave.is_paid_work_for(profile.employment_type)
                    else STANDARD * min(leave.fraction, Decimal("1"))
                )
                overtime += max(Decimal("0"), total + occupied - STANDARD)
        items.append(
            {
                "user_id": user.id,
                "name": user.name,
                "job_title": profile.job_title,
                "timesheet": timesheet_payload(timesheet),
                "status": timesheet.status if timesheet else "missing",
                "hours": float(hours),
                "overtime_hours": float(overtime),
                "absence_days": float(
                    sum(
                        (leave.fraction for leave in user_leaves.values()), Decimal("0")
                    )
                ),
                "can_decide": actor.can_approve(profile),
            }
        )
        if missing_before is not None:
            open_month = timesheet is None or timesheet.status == "draft"
            items[-1]["missing_dates"] = (
                [
                    day.isoformat()
                    for day in past_working_days
                    if employed_on(profile, day)
                    and not (
                        timesheet is not None
                        and sums.get((timesheet.id, day), Decimal("0")) > 0
                    )
                    and not (day in user_leaves and user_leaves[day].is_full)
                ]
                if open_month
                else []
            )
    order = {"submitted": 0, "draft": 1, "missing": 2, "approved": 3}
    items.sort(key=lambda item: (order.get(item["status"], 9), item["name"].lower()))
    return items


async def subject_for(
    db: AsyncSession, user_id: int
) -> tuple[Optional[User], Optional[EmployeeProfile]]:
    row = (
        await db.execute(
            select(User, EmployeeProfile)
            .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
            .where(User.id == user_id)
        )
    ).first()
    if row is None:
        return None, None
    return row[0], row[1]


async def history(
    db: AsyncSession, *, user_id: int, months: int = 12
) -> list[dict[str, Any]]:
    """Archiwum: ostatnie timesheety osoby z sumą godzin."""

    rows = await db.execute(
        select(
            Timesheet.id,
            Timesheet.year,
            Timesheet.month,
            Timesheet.status,
            Timesheet.approved_at,
            func.coalesce(func.sum(TimesheetEntry.hours), 0),
        )
        .outerjoin(TimesheetEntry, TimesheetEntry.timesheet_id == Timesheet.id)
        .where(Timesheet.user_id == user_id)
        .group_by(Timesheet.id)
        .order_by(Timesheet.year.desc(), Timesheet.month.desc())
        .limit(months)
    )
    return [
        {
            "id": ts_id,
            "year": year,
            "month": month,
            "status": status,
            "approved_at": approved_at,
            "hours": float(total),
        }
        for ts_id, year, month, status, approved_at, total in rows.all()
    ]
