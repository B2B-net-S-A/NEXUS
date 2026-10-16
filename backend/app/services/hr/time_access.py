"""Kto widzi, edytuje i akceptuje timesheet („Mój miesiąc”).

* **akceptuje** — przełożony z kartoteki dla swoich ludzi, Kadry
  (``people_admin``) i admin dla wszystkich; nikt siebie (także admin —
  w Compassie admin zatwierdzał własny timesheet),
* **nadgodziny** — osoba z ``can_log_overtime`` w kartotece albo Kadry/admin,
* **czyta PDF** — sama osoba, akceptujący w zakresie, Płace, Kadry, admin.

Przełożony widzi godziny zespołu, nie stawki (stawek w tym module nie ma).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import people


@dataclass(frozen=True)
class Actor:
    user: User
    profile: Optional[EmployeeProfile]
    is_admin: bool
    people_admin: bool
    payroll: bool
    report_ids: frozenset[int] = field(default_factory=frozenset)

    @property
    def user_id(self) -> int:
        return self.user.id

    @property
    def overtime_allowed(self) -> bool:
        if self.is_admin or self.people_admin:
            return True
        return bool(self.profile and self.profile.can_log_overtime)

    @property
    def approves_everyone(self) -> bool:
        return self.is_admin or self.people_admin

    @property
    def is_approver(self) -> bool:
        return self.approves_everyone or bool(self.report_ids)

    def can_approve(self, subject: EmployeeProfile) -> bool:
        if subject.user_id == self.user_id:
            return False
        if self.approves_everyone:
            return True
        return subject.manager_user_id == self.user_id

    def can_read(self, subject: EmployeeProfile) -> bool:
        return (
            subject.user_id == self.user_id
            or self.payroll
            or self.approves_everyone
            or subject.manager_user_id == self.user_id
        )


async def load_actor(db: AsyncSession, user: User) -> Actor:
    return Actor(
        user=user,
        profile=await people.profile_of(db, user.id),
        is_admin=user.has_role(UserRole.admin),
        people_admin=has_permission(user, ProductAction.people_admin),
        payroll=has_permission(user, ProductAction.payroll),
        report_ids=frozenset(await people.direct_report_ids(db, user.id)),
    )


async def users_with_permission(db: AsyncSession, action: ProductAction) -> list[User]:
    """Aktywne konta z uprawnieniem (admin ma wszystkie)."""

    from app.services.effective_access import resolve_effective_access

    users = list(
        await db.scalars(select(User).where(User.is_active.is_(True)).order_by(User.id))
    )
    await resolve_effective_access(db, users)
    return [user for user in users if has_permission(user, action)]


async def approval_recipients(db: AsyncSession, subject_user_id: int) -> list[int]:
    """Kto dostaje „timesheet do akceptacji”: przełożony, a bez niego Kadry.

    Przełożony liczy się tylko z aktywnym kontem i bez statusu „exited”
    (w Compassie zastępczo szło do wszystkich adminów, także tych, którzy
    odeszli). Sama osoba nie dostaje własnego timesheetu do akceptacji.
    """

    profile = await people.profile_of(db, subject_user_id)
    manager_id = profile.manager_user_id if profile else None
    if manager_id is not None and manager_id != subject_user_id:
        manager = await db.get(User, manager_id)
        manager_profile = await people.profile_of(db, manager_id)
        exited = (
            manager_profile is not None
            and manager_profile.employment_status == "exited"
        )
        if manager is not None and manager.is_active and not exited:
            return [manager_id]
    holders = await users_with_permission(db, ProductAction.people_admin)
    return [user.id for user in holders if user.id != subject_user_id]
