"""Kto widzi, edytuje i akceptuje timesheet („Mój miesiąc”).

* **akceptuje** — przełożony z kartoteki dla swoich ludzi, Kadry
  (``people_admin``) i admin dla wszystkich; nikt siebie (także admin —
  w Compassie admin zatwierdzał własny timesheet); zastępca przełożonego,
  który jest dziś na urlopie, dla podwładnych tego przełożonego
  (``leave_substitute``) — bez rodzaju nieobecności w dniach (D6),
* **nadgodziny** — osoba z ``can_log_overtime`` w kartotece albo Kadry/admin,
* **czyta PDF** — sama osoba, akceptujący w zakresie, Płace, Kadry, admin.

Przełożony widzi godziny zespołu, nie stawki (stawek w tym module nie ma).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import leave_substitute, people


@dataclass(frozen=True)
class Actor:
    user: User
    profile: Optional[EmployeeProfile]
    is_admin: bool
    people_admin: bool
    payroll: bool
    report_ids: frozenset[int] = field(default_factory=frozenset)
    #: Podwładni przełożonych, których osoba zastępuje dziś → za kogo.
    covered: dict[int, leave_substitute.Cover] = field(default_factory=dict)

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
        return self.approves_everyone or bool(self.report_ids) or bool(self.covered)

    @property
    def covered_ids(self) -> frozenset[int]:
        return frozenset(self.covered)

    def substitute_for(
        self, subject: EmployeeProfile
    ) -> Optional[leave_substitute.Cover]:
        """Zastępstwo, przez które osoba decyduje o ``subject`` (``None`` = własny
        zespół, Kadry, admin albo brak prawa)."""

        if self.approves_everyone or subject.manager_user_id == self.user_id:
            return None
        return self.covered.get(subject.user_id)

    def sees_leave_type(self, subject: EmployeeProfile) -> bool:
        """D6: rodzaj nieobecności w dniach timesheetu — nie dla zastępcy."""

        return self.substitute_for(subject) is None

    def cover_details(self, subject: EmployeeProfile) -> dict[str, Any]:
        """Do śladu decyzji: „w zastępstwie za …” (puste przy własnym prawie)."""

        cover = self.substitute_for(subject)
        if cover is None:
            return {}
        return {
            "as_substitute_for_user_id": cover.manager_user_id,
            "as_substitute_for": f"w zastępstwie za {cover.manager_name}",
        }

    def can_approve(self, subject: EmployeeProfile) -> bool:
        if subject.user_id == self.user_id:
            return False
        if self.approves_everyone:
            return True
        return (
            subject.manager_user_id == self.user_id or subject.user_id in self.covered
        )

    def can_read(self, subject: EmployeeProfile) -> bool:
        return (
            subject.user_id == self.user_id
            or self.payroll
            or self.approves_everyone
            or subject.manager_user_id == self.user_id
            or subject.user_id in self.covered
        )


async def load_actor(db: AsyncSession, user: User) -> Actor:
    return Actor(
        user=user,
        profile=await people.profile_of(db, user.id),
        is_admin=user.has_role(UserRole.admin),
        people_admin=has_permission(user, ProductAction.people_admin),
        payroll=has_permission(user, ProductAction.payroll),
        report_ids=frozenset(await people.direct_report_ids(db, user.id)),
        covered=await leave_substitute.covered_reports(db, user.id, business_today()),
    )


async def is_time_approver(db: AsyncSession, user: User) -> bool:
    """Bramka kolejki timesheetów: Kadry, admin, przełożony albo zastępca
    przełożonego, który jest dziś na urlopie."""

    if user.has_role(UserRole.admin) or has_permission(
        user, ProductAction.people_admin
    ):
        return True
    if await people.direct_report_ids(db, user.id):
        return True
    return bool(await leave_substitute.covered_reports(db, user.id, business_today()))


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
    Przełożony dziś na urlopie z zastępcą — dostaje też zastępca.
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
            stand_in = await leave_substitute.stand_in_for(
                db, manager_id, business_today()
            )
            if stand_in is not None and stand_in.user_id != subject_user_id:
                return [manager_id, stand_in.user_id]
            return [manager_id]
    holders = await users_with_permission(db, ProductAction.people_admin)
    return [user.id for user in holders if user.id != subject_user_id]
