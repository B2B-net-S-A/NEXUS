"""Kto dostaje sprawę osoby i kto o niej decyduje — jedna reguła (17.10.2026).

``supervisor_of`` liczy przełożonego osoby dla urlopów (wniosek, zgłoszenie
z B2B i zlecenia, anulowanie), czasu (timesheet do akceptacji) i zadań:

1. przełożony z kartoteki — gdy ma aktywne konto i nie odszedł (kartoteka
   ``exited``); konto bez kartoteki (np. zarząd) się liczy,
2. head pionu osoby (``app_settings['hr_divisions']``) — ta sama zasada
   „aktywny i nie odszedł”, nigdy sama osoba,
3. Kadry (uprawnienie „Kadry” bez adminów), a bez Kadr — admini; nigdy sama
   osoba.

Zastępca nieobecnego przełożonego (``leave_substitute``) dochodzi tylko przy
przełożonym z punktu 1. ``division_charges`` to ta sama reguła od strony
heada: osoby jego pionu bez żywego przełożonego. Kto dostaje sprawę do
decyzji, ten o niej decyduje — head akceptuje wnioski i timesheety tych osób.

Do 17.10.2026 urlop nie sprawdzał ``exited`` i znał heada tylko przy
zgłoszeniach z B2B, a czas nie znał heada i liczył Kadry razem z adminami.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import leave_substitute, people

SupervisorKind = Literal["manager", "division_head", "people_admin"]
PEOPLE_ADMIN_LABEL = "Kadry"


@dataclass(frozen=True)
class Supervisor:
    kind: SupervisorKind
    #: Kto dostaje sprawę do decyzji (bez samej osoby).
    user_ids: tuple[int, ...]
    #: Imię przełożonego albo heada, przy Kadrach — „Kadry”.
    label: str
    #: Zastępca przełożonego, który jest dziś na urlopie (tylko ``manager``).
    stand_in: Optional[leave_substitute.StandIn] = None


async def users_with_permission(db: AsyncSession, action: ProductAction) -> list[User]:
    """Aktywne konta z uprawnieniem (admin ma wszystkie)."""

    from app.services.effective_access import resolve_effective_access

    users = list(
        await db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id))
    )
    await resolve_effective_access(db, users)
    return [user for user in users if has_permission(user, action)]


async def people_admin_ids(db: AsyncSession) -> list[int]:
    """Kadry (uprawnienie „Kadry” bez adminów); brak Kadr → admini."""

    holders = await users_with_permission(db, ProductAction.people_admin)
    hr = [user.id for user in holders if not user.has_role(UserRole.admin)]
    if hr:
        return hr
    return await admin_ids(db)


async def admin_ids(db: AsyncSession) -> list[int]:
    """Aktywni admini (rola główna albo dodatkowa)."""

    users = await db.scalars(
        select(User).where(User.is_active.is_(True)).order_by(User.id)
    )
    return [user.id for user in users if user.has_role(UserRole.admin)]


async def kadry_ids(db: AsyncSession, *, exclude: Optional[int]) -> list[int]:
    """Kadry bez ``exclude``; gdy to jedyna osoba z Kadr — admini.

    Wniosek jedynej osoby z Kadr bez przełożonego idzie do adminów — sama
    o nim nie zdecyduje, a pusta lista znaczyła sprawę, o której nikt nie wie.
    """

    hr = [uid for uid in await people_admin_ids(db) if uid != exclude]
    if hr:
        return hr
    return [uid for uid in await admin_ids(db) if uid != exclude]


async def _live(
    db: AsyncSession, user_id: Optional[int], subject_id: Optional[int]
) -> Optional[User]:
    """Konto, które może prowadzić sprawy osoby: aktywne, nie odeszło, nie ona."""

    if user_id is None or user_id == subject_id:
        return None
    user = await db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    profile = await people.profile_of(db, user_id)
    if profile is not None and profile.employment_status == "exited":
        return None
    return user


async def _division_head(
    db: AsyncSession, profile: Optional[EmployeeProfile]
) -> Optional[User]:
    if profile is None or not profile.division:
        return None
    from app.services.hr.structure import load_division_heads

    head_id = (await load_division_heads(db)).get(profile.division)
    return await _live(db, head_id, profile.user_id)


async def supervisor_of(
    db: AsyncSession, profile: Optional[EmployeeProfile], today: Optional[date] = None
) -> Supervisor:
    """Przełożony osoby według jednej reguły (docstring modułu).

    ``today`` (kalendarz firmy) dokłada zastępcę przełożonego, który jest
    tego dnia na urlopie; bez niego zastępcy się nie szuka (podgląd, etykieta).
    """

    subject_id = profile.user_id if profile is not None else None
    manager = await _live(
        db, profile.manager_user_id if profile is not None else None, subject_id
    )
    if manager is not None:
        stand_in = (
            await leave_substitute.stand_in_for(db, manager.id, today)
            if today is not None
            else None
        )
        if stand_in is not None and stand_in.user_id == subject_id:
            stand_in = None
        return Supervisor("manager", (manager.id,), manager.name, stand_in)
    head = await _division_head(db, profile)
    if head is not None:
        return Supervisor("division_head", (head.id,), head.name)
    return Supervisor(
        "people_admin",
        tuple(await kadry_ids(db, exclude=subject_id)),
        PEOPLE_ADMIN_LABEL,
    )


async def division_charges(db: AsyncSession, actor_id: int) -> set[int]:
    """Osoby, których przełożonym według ``supervisor_of`` jest head ``actor_id``:
    jego pion, bez żywego przełożonego, bez osób, które odeszły, i bez niego."""

    from app.services.hr.structure import load_division_heads

    divisions = [
        key for key, head in (await load_division_heads(db)).items() if head == actor_id
    ]
    if not divisions or await _live(db, actor_id, None) is None:
        return set()
    manager = aliased(User)
    manager_profile = aliased(EmployeeProfile)
    rows = await db.scalars(
        select(EmployeeProfile.user_id)
        .outerjoin(manager, manager.id == EmployeeProfile.manager_user_id)
        .outerjoin(
            manager_profile,
            manager_profile.user_id == EmployeeProfile.manager_user_id,
        )
        .where(
            EmployeeProfile.division.in_(divisions),
            EmployeeProfile.employment_status != "exited",
            EmployeeProfile.user_id != actor_id,
            or_(
                EmployeeProfile.manager_user_id.is_(None),
                EmployeeProfile.manager_user_id == EmployeeProfile.user_id,
                manager.is_active.is_not(True),
                manager_profile.employment_status == "exited",
            ),
        )
    )
    return set(rows)


__all__ = [
    "PEOPLE_ADMIN_LABEL",
    "Supervisor",
    "admin_ids",
    "division_charges",
    "kadry_ids",
    "people_admin_ids",
    "supervisor_of",
    "users_with_permission",
]
