"""Kalendarz zespołu — miesiąc, osoby z kartoteką, nieobecności (D6).

Lista osób według reguły miesięcznej z Compassa: osoba, która odeszła 20-go,
jest w kalendarzu do końca miesiąca (``exited`` z ostatnim dniem pracy w tym
miesiącu albo później). Każdy widzi „nieobecność”; rodzaj, notatkę i wnioski
oczekujące widzi tylko krąg D6 — sama osoba, jej przełożony, Kadry i admin.

Obok nieobecności kalendarz pokazuje pracę zdalną i delegację z wyjątków
obecności „Mojego miesiąca” (``attendance_days``: ``active`` + ``remote``
i ``business_trip``) — tylko do odczytu i tylko przy module czasu otwartym dla
patrzącego. To nie są rodzaje nieobecności (D6 ich nie dotyczy), notatki dnia
nie wychodzą. Dzień domyślnej pracy zdalnej z kartoteki (bez wiersza) się
nie pokazuje — kalendarz mówi o wyjątkach, jak „Mój miesiąc”. Filtr
„nieobecni / zdalnie” liczy front z tych danych (jak Compass,
``VacationCalendar``).
"""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.hr_time import AttendanceDay
from app.models.user import User
from app.services.hr.absence import month_absences
from app.services.hr.calendar import load_calendar, month_days
from app.services.hr.leave_policy import Actor, can_see_type, type_label
from app.services.hr.people import DIRECTORY_STATUSES

ABSENCE_LABEL = "Nieobecność"


async def team_calendar(
    db: AsyncSession,
    *,
    viewer: Actor,
    year: int,
    month: int,
    department: Optional[str] = None,
    team_only: bool = False,
    today: date,
    with_presence: bool = False,
) -> dict[str, Any]:
    days = month_days(year, month)
    first, last = days[0], days[-1]
    calendar = await load_calendar(db, first, last)
    statement = (
        select(User, EmployeeProfile)
        .join(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(
            or_(
                EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES),
                and_(
                    EmployeeProfile.employment_status == "exited",
                    EmployeeProfile.last_working_day >= first,
                ),
            ),
            or_(
                EmployeeProfile.work_start_date.is_(None),
                EmployeeProfile.work_start_date <= last,
            ),
        )
        .order_by(User.name, User.id)
    )
    rows = (await db.execute(statement)).all()
    departments = sorted({p.department for _, p in rows if p.department})
    if team_only:
        rows = [
            (u, p)
            for u, p in rows
            if p.manager_user_id == viewer.user_id or u.id == viewer.user_id
        ]
    if department:
        rows = [(u, p) for u, p in rows if p.department == department]

    managers = {u.id: p.manager_user_id for u, p in rows}
    forms = {u.id: p.employment_type for u, p in rows}
    in_d6 = {
        uid
        for uid, manager_id in managers.items()
        if can_see_type(viewer, subject_user_id=uid, subject_manager_id=manager_id)
    }
    absences = await month_absences(db, managers.keys(), first, last, pending_for=in_d6)
    substitute_ids = {a.substitute_user_id for a in absences if a.substitute_user_id}
    names: dict[int, str] = {}
    if substitute_ids:
        names = dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(substitute_ids))
                )
            ).all()
        )
    by_user: dict[int, list[dict[str, Any]]] = {}
    for absence in absences:
        visible = absence.user_id in in_d6
        by_user.setdefault(absence.user_id, []).append(
            {
                "id": absence.id if visible else None,
                "start_date": absence.start.isoformat(),
                "end_date": absence.end.isoformat(),
                "half_day": absence.half_day,
                "status": absence.status,
                # Słowa formy (D4): „Przerwa w świadczeniu usług” na B2B.
                "label": type_label(absence.leave_type, forms.get(absence.user_id))
                if visible
                else ABSENCE_LABEL,
                "leave_type": absence.leave_type if visible else None,
                "substitute_user_id": absence.substitute_user_id,
                "substitute_name": names.get(absence.substitute_user_id)
                if absence.substitute_user_id
                else None,
            }
        )
    presence = (
        await presence_between(db, list(managers), first, last) if with_presence else {}
    )
    return {
        "month": f"{year:04d}-{month:02d}",
        "presence_shown": with_presence,
        "today": today.isoformat(),
        "days": [
            {
                "date": day.isoformat(),
                "weekday": day.weekday(),
                "kind": calendar.kind(day),
                "name": calendar.day_name(day),
            }
            for day in days
        ],
        "departments": departments,
        "people": [
            {
                "user_id": user.id,
                "name": user.name,
                "department": profile.department,
                "job_title": profile.job_title,
                "is_me": user.id == viewer.user_id,
                "type_visible": user.id in in_d6,
                "absences": by_user.get(user.id, []),
                "presence": presence.get(user.id, []),
            }
            for user, profile in rows
        ],
    }


async def presence_between(
    db: AsyncSession, user_ids: list[int], first: date, last: date
) -> dict[int, list[dict[str, str]]]:
    """Praca zdalna i delegacja z ``attendance_days`` w okresie (bez notatek).

    Czyta też kolumna „Dziś” katalogu ``GET /api/hr/people`` (jeden dzień).
    """

    if not user_ids:
        return {}
    rows = await db.execute(
        select(
            AttendanceDay.user_id,
            AttendanceDay.day,
            AttendanceDay.status,
            AttendanceDay.location,
        )
        .where(
            AttendanceDay.user_id.in_(user_ids),
            AttendanceDay.day >= first,
            AttendanceDay.day <= last,
        )
        .order_by(AttendanceDay.user_id, AttendanceDay.day)
    )
    out: dict[int, list[dict[str, str]]] = {}
    for user_id, day, status, location in rows.all():
        kind = (
            "business_trip"
            if status == "business_trip"
            else ("remote" if status == "active" and location == "remote" else None)
        )
        if kind is None:
            continue
        out.setdefault(user_id, []).append({"date": day.isoformat(), "kind": kind})
    return out
