"""Katalog ludzi i kartoteka pracownika („Ludzie w NEXUSIE”, krok E0).

Zakres widoczności (rozstrzyga ``viewer_scope``):

* **wizytówka** — każdy, kto ma kartotekę albo Kadry: imię, stanowisko, dział,
  przełożony, miejsce pracy, telefon służbowy, status (bez formy umowy i dat),
* **pełna kartoteka** — sama osoba, jej przełożony (bezpośredni) i Kadry,
* stawki i kwoty — nigdy tutaj (moduł Płace, uprawnienie ``payroll``).

Zapis kartoteki tylko przez Kadry (``people_admin``); każda zmiana zostawia
wiersz w ``hr_audit_events`` z nazwami pól.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import CompanyDayOff, EmployeeProfile, LeaveEntitlement
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import audit
from app.services.hr_foundation_schema import (
    EMPLOYMENT_STATUSES,
    EMPLOYMENT_TYPES,
    LOCATIONS,
)

Scope = Literal["none", "card", "full"]

#: Statusy widoczne w katalogu (osoba pracuje albo kończy).
DIRECTORY_STATUSES: tuple[str, ...] = ("onboarding", "active", "offboarding")

#: Pola kartoteki, które Kadry mogą zmieniać.
EDITABLE_FIELDS: tuple[str, ...] = (
    "manager_user_id",
    "employment_type",
    "employment_status",
    "hired_on",
    "work_start_date",
    "last_working_day",
    "default_location",
    "timesheet_required",
    "can_log_overtime",
    "job_title",
    "department",
    "phone",
)

_MAX_MANAGER_CHAIN = 50


class HrPeopleError(ValueError):
    """Błąd walidacji z komunikatem dla użytkownika (po polsku)."""


def is_people_admin(user: User) -> bool:
    return has_permission(user, ProductAction.people_admin)


async def profile_of(db: AsyncSession, user_id: int) -> Optional[EmployeeProfile]:
    return await db.scalar(
        select(EmployeeProfile).where(EmployeeProfile.user_id == user_id)
    )


async def has_live_profile(db: AsyncSession, user_id: int) -> bool:
    status = await db.scalar(
        select(EmployeeProfile.employment_status).where(
            EmployeeProfile.user_id == user_id
        )
    )
    return status is not None and status != "exited"


async def direct_report_ids(db: AsyncSession, manager_user_id: int) -> set[int]:
    rows = await db.scalars(
        select(EmployeeProfile.user_id).where(
            EmployeeProfile.manager_user_id == manager_user_id,
            EmployeeProfile.employment_status != "exited",
        )
    )
    return set(rows)


async def viewer_scope(
    db: AsyncSession, viewer: User, subject: EmployeeProfile
) -> Scope:
    if viewer.id == subject.user_id or is_people_admin(viewer):
        return "full"
    if subject.manager_user_id is not None and subject.manager_user_id == viewer.id:
        return "full"
    if await has_live_profile(db, viewer.id):
        return "card"
    return "none"


@dataclass(frozen=True)
class PersonRow:
    user: User
    profile: EmployeeProfile
    manager_name: Optional[str]


async def directory(db: AsyncSession) -> list[PersonRow]:
    rows = (
        await db.execute(
            select(EmployeeProfile, User)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.employment_status.in_(DIRECTORY_STATUSES))
            .order_by(User.name, User.id)
        )
    ).all()
    manager_ids = {p.manager_user_id for p, _ in rows if p.manager_user_id}
    names: dict[int, str] = {}
    if manager_ids:
        names = dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(manager_ids))
                )
            ).all()
        )
    return [
        PersonRow(
            user=user,
            profile=profile,
            manager_name=names.get(profile.manager_user_id)
            if profile.manager_user_id
            else None,
        )
        for profile, user in rows
    ]


def card_payload(row: PersonRow) -> dict[str, Any]:
    profile = row.profile
    return {
        "user_id": row.user.id,
        "name": row.user.name,
        "email": row.user.email,
        "job_title": profile.job_title,
        "department": profile.department,
        "phone": profile.phone,
        "default_location": profile.default_location,
        "employment_status": profile.employment_status,
        "manager_user_id": profile.manager_user_id,
        "manager_name": row.manager_name,
    }


def full_payload(row: PersonRow) -> dict[str, Any]:
    profile = row.profile
    return {
        **card_payload(row),
        "employment_type": profile.employment_type,
        "hired_on": profile.hired_on,
        "work_start_date": profile.work_start_date,
        "last_working_day": profile.last_working_day,
        "timesheet_required": profile.timesheet_required,
        "can_log_overtime": profile.can_log_overtime,
        "roles": [role.value for role in row.user.get_all_roles()],
    }


async def person_row(db: AsyncSession, user_id: int) -> Optional[PersonRow]:
    found = (
        await db.execute(
            select(EmployeeProfile, User)
            .join(User, User.id == EmployeeProfile.user_id)
            .where(EmployeeProfile.user_id == user_id)
        )
    ).first()
    if found is None:
        return None
    profile, user = found
    manager_name = None
    if profile.manager_user_id:
        manager_name = await db.scalar(
            select(User.name).where(User.id == profile.manager_user_id)
        )
    return PersonRow(user=user, profile=profile, manager_name=manager_name)


async def users_without_profile(db: AsyncSession) -> list[dict[str, Any]]:
    """Aktywne konta bez kartoteki (do „Dodaj osobę” w Kadrach).

    Konta techniczne (``automation``) i stary podgląd (``user``) pomijamy —
    to nie są ludzie zatrudnieni w firmie.
    """

    rows = await db.scalars(
        select(User)
        .outerjoin(EmployeeProfile, EmployeeProfile.user_id == User.id)
        .where(User.is_active.is_(True), EmployeeProfile.id.is_(None))
        .order_by(User.name, User.id)
    )
    skip = {UserRole.automation, UserRole.user}
    return [
        {"user_id": user.id, "name": user.name, "email": user.email}
        for user in rows
        if not set(user.get_all_roles()) & skip
    ]


async def _validate_manager(
    db: AsyncSession, *, user_id: int, manager_user_id: Optional[int]
) -> None:
    if manager_user_id is None:
        return
    if manager_user_id == user_id:
        raise HrPeopleError("Osoba nie może być swoim własnym przełożonym.")
    manager = await db.get(User, manager_user_id)
    if manager is None or not manager.is_active:
        raise HrPeopleError("Wybrany przełożony nie ma aktywnego konta.")
    # Cykl (A → B → A) zablokowałby akceptacje: nikt nie byłby „nad” nikim.
    seen = {user_id}
    current: Optional[int] = manager_user_id
    for _ in range(_MAX_MANAGER_CHAIN):
        if current is None:
            return
        if current in seen:
            raise HrPeopleError(
                "Ten wybór tworzy pętlę przełożonych — sprawdź, komu podlega "
                "wybrana osoba."
            )
        seen.add(current)
        current = await db.scalar(
            select(EmployeeProfile.manager_user_id).where(
                EmployeeProfile.user_id == current
            )
        )


def _validate_values(values: dict[str, Any]) -> None:
    if (
        "employment_type" in values
        and values["employment_type"] not in EMPLOYMENT_TYPES
    ):
        raise HrPeopleError("Nieznana forma zatrudnienia.")
    if (
        "employment_status" in values
        and values["employment_status"] not in EMPLOYMENT_STATUSES
    ):
        raise HrPeopleError("Nieznany status zatrudnienia.")
    if "default_location" in values and values["default_location"] not in LOCATIONS:
        raise HrPeopleError("Nieznane domyślne miejsce pracy.")
    start = values.get("work_start_date")
    last = values.get("last_working_day")
    if start and last and last < start:
        raise HrPeopleError("Ostatni dzień pracy nie może być przed datą startu.")


async def create_profile(
    db: AsyncSession, *, user_id: int, values: dict[str, Any], actor: User
) -> EmployeeProfile:
    target = await db.get(User, user_id)
    if target is None:
        raise LookupError(user_id)
    if await profile_of(db, user_id) is not None:
        raise HrPeopleError("Ta osoba ma już kartotekę.")
    clean = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    _validate_values(clean)
    await _validate_manager(
        db, user_id=user_id, manager_user_id=clean.get("manager_user_id")
    )
    profile = EmployeeProfile(user_id=user_id, updated_by=actor.id, **clean)
    db.add(profile)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="employee_profile",
        entity_id=profile.id,
        action="profile_created",
        details={"fields": sorted(clean)},
    )
    return profile


async def update_profile(
    db: AsyncSession, *, user_id: int, values: dict[str, Any], actor: User
) -> EmployeeProfile:
    profile = await profile_of(db, user_id)
    if profile is None:
        raise LookupError(user_id)
    clean = {key: value for key, value in values.items() if key in EDITABLE_FIELDS}
    merged = {
        "work_start_date": profile.work_start_date,
        "last_working_day": profile.last_working_day,
        **clean,
    }
    _validate_values({**clean, **merged})
    if "manager_user_id" in clean:
        await _validate_manager(
            db, user_id=user_id, manager_user_id=clean["manager_user_id"]
        )
    changed = sorted(
        key for key, value in clean.items() if getattr(profile, key) != value
    )
    for key in changed:
        setattr(profile, key, clean[key])
    if changed:
        profile.updated_by = actor.id
        audit.record(
            db,
            actor_user_id=actor.id,
            subject_user_id=user_id,
            entity_type="employee_profile",
            entity_id=profile.id,
            action="profile_updated",
            details={"fields": changed},
        )
    return profile


async def entitlements_of(db: AsyncSession, user_id: int) -> list[LeaveEntitlement]:
    rows = await db.scalars(
        select(LeaveEntitlement)
        .where(LeaveEntitlement.user_id == user_id)
        .order_by(LeaveEntitlement.year.desc())
    )
    return list(rows)


async def set_entitlement(
    db: AsyncSession,
    *,
    user_id: int,
    year: int,
    entitlement_days: Optional[Decimal],
    carried_over_days: Decimal,
    used_initial_days: Decimal,
    reason: Optional[str],
    actor: User,
) -> LeaveEntitlement:
    if await profile_of(db, user_id) is None:
        raise LookupError(user_id)
    for value in (entitlement_days, carried_over_days, used_initial_days):
        if value is not None and (value < 0 or value > 366):
            raise HrPeopleError("Liczba dni musi być między 0 a 366.")
        if value is not None and (value * 2) % 1 != 0:
            raise HrPeopleError("Dni podaje się w pełnych dniach albo połówkach.")
    row = await db.scalar(
        select(LeaveEntitlement).where(
            LeaveEntitlement.user_id == user_id, LeaveEntitlement.year == year
        )
    )
    if row is None:
        row = LeaveEntitlement(user_id=user_id, year=year)
        db.add(row)
    row.entitlement_days = entitlement_days
    row.carried_over_days = carried_over_days
    row.used_initial_days = used_initial_days
    row.reason = reason
    row.set_by = actor.id
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=user_id,
        entity_type="leave_entitlement",
        entity_id=row.id,
        action="entitlement_set",
        details={"year": year},
    )
    return row


async def days_off(
    db: AsyncSession, *, year: Optional[int] = None
) -> list[CompanyDayOff]:
    statement = select(CompanyDayOff).order_by(CompanyDayOff.day)
    if year is not None:
        statement = statement.where(
            CompanyDayOff.day >= date(year, 1, 1),
            CompanyDayOff.day <= date(year, 12, 31),
        )
    return list(await db.scalars(statement))


async def add_day_off(
    db: AsyncSession, *, day: date, name: str, kind: str, actor: User
) -> CompanyDayOff:
    name = name.strip()
    if not name:
        raise HrPeopleError("Podaj nazwę dnia wolnego.")
    if kind not in ("company", "bridge"):
        raise HrPeopleError("Nieznany rodzaj dnia wolnego.")
    if day.weekday() >= 5:
        raise HrPeopleError("Weekend i tak jest wolny — wybierz dzień roboczy.")
    if await db.scalar(select(CompanyDayOff.id).where(CompanyDayOff.day == day)):
        raise HrPeopleError("Ten dzień jest już na liście dni wolnych.")
    row = CompanyDayOff(day=day, name=name[:120], kind=kind, created_by=actor.id)
    db.add(row)
    await db.flush()
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="company_day_off",
        entity_id=row.id,
        action="day_off_added",
        details={"day": day.isoformat()},
    )
    return row


async def remove_day_off(db: AsyncSession, *, day_off_id: int, actor: User) -> None:
    row = await db.get(CompanyDayOff, day_off_id)
    if row is None:
        raise LookupError(day_off_id)
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=None,
        entity_type="company_day_off",
        entity_id=row.id,
        action="day_off_removed",
        details={"day": row.day.isoformat()},
    )
    await db.delete(row)
