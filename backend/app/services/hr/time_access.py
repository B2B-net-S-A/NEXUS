"""Kto widzi, edytuje i akceptuje timesheet („Mój miesiąc”).

* **akceptuje** — przełożony z kartoteki dla swoich ludzi, Kadry
  (``people_admin``), „Raporty godzin” (``timesheets``, 28.10.2026) i admin
  dla wszystkich; nikt siebie (także admin —
  w Compassie admin zatwierdzał własny timesheet); zastępca przełożonego,
  który jest dziś na urlopie, dla podwładnych tego przełożonego
  (``leave_substitute``) — bez rodzaju nieobecności w dniach (D6); head pionu
  dla osób swojego pionu bez żywego przełożonego (``recipients``, ta sama
  reguła co przy urlopach),
* **rodzaj nieobecności** w dniach (D6) — osoba, przełożony, head pionu,
  Kadry, admin; „Raporty godzin” bez kręgu D6 widzą „nieobecność”, jak
  zastępca,
* **nadgodziny** — osoba z ``can_log_overtime`` w kartotece albo Kadry/admin,
* **czyta PDF** — sama osoba, akceptujący w zakresie, Płace, Kadry, admin.

Przełożony widzi godziny zespołu, nie stawki (stawek w tym module nie ma).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission
from app.services.hr import leave_substitute, people
from app.services.hr.recipients import (
    division_charges,
    supervisor_of,
    users_with_permission,
)


@dataclass(frozen=True)
class Actor:
    user: User
    profile: Optional[EmployeeProfile]
    is_admin: bool
    people_admin: bool
    payroll: bool
    #: „Raporty godzin: akceptacja całej firmy” — bez reszty Kadr.
    timesheets: bool = False
    report_ids: frozenset[int] = field(default_factory=frozenset)
    #: Podwładni przełożonych, których osoba zastępuje dziś → za kogo.
    covered: dict[int, leave_substitute.Cover] = field(default_factory=dict)
    #: Osoby pionu bez żywego przełożonego, gdy osoba jest headem pionu.
    charges: frozenset[int] = field(default_factory=frozenset)

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
        return self.is_admin or self.people_admin or self.timesheets

    @property
    def is_approver(self) -> bool:
        return (
            self.approves_everyone
            or bool(self.report_ids)
            or bool(self.covered)
            or bool(self.charges)
        )

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
        """D6: rodzaj nieobecności w dniach timesheetu — nie dla zastępcy
        ani dla samych „Raportów godzin” spoza własnego zespołu."""

        if self.is_admin or self.people_admin:
            return True
        if self.timesheets:
            return (
                subject.user_id == self.user_id
                or subject.manager_user_id == self.user_id
                or subject.user_id in self.charges
            )
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
            subject.manager_user_id == self.user_id
            or subject.user_id in self.covered
            or subject.user_id in self.charges
        )

    def can_read(self, subject: EmployeeProfile) -> bool:
        return (
            subject.user_id == self.user_id or self.payroll or self.can_approve(subject)
        )


async def load_actor(db: AsyncSession, user: User) -> Actor:
    is_admin = user.has_role(UserRole.admin)
    people_admin = has_permission(user, ProductAction.people_admin)
    return Actor(
        user=user,
        profile=await people.profile_of(db, user.id),
        is_admin=is_admin,
        people_admin=people_admin,
        payroll=has_permission(user, ProductAction.payroll),
        timesheets=has_permission(user, ProductAction.timesheets),
        report_ids=frozenset(await people.direct_report_ids(db, user.id)),
        covered=await leave_substitute.covered_reports(db, user.id, business_today()),
        # Kadry i admin akceptują wszystkich — zakres heada nic im nie dokłada.
        charges=frozenset()
        if is_admin or people_admin
        else frozenset(await division_charges(db, user.id)),
    )


async def is_time_approver(db: AsyncSession, user: User) -> bool:
    """Bramka kolejki timesheetów: Kadry, „Raporty godzin”, admin, przełożony,
    zastępca przełożonego, który jest dziś na urlopie, albo head pionu
    z osobami bez żywego przełożonego."""

    if user.has_role(UserRole.admin) or any(
        has_permission(user, p)
        for p in (ProductAction.people_admin, ProductAction.timesheets)
    ):
        return True
    if await people.direct_report_ids(db, user.id):
        return True
    if await leave_substitute.covered_reports(db, user.id, business_today()):
        return True
    return bool(await division_charges(db, user.id))


async def approval_recipients(db: AsyncSession, subject_user_id: int) -> list[int]:
    """Kto dostaje „timesheet do akceptacji”: przełożony według jednej reguły
    (``recipients.supervisor_of``: przełożony, head pionu, Kadry), a przy
    przełożonym dziś na urlopie — także jego zastępca. Nigdy sama osoba."""

    profile = await people.profile_of(db, subject_user_id)
    supervisor = await supervisor_of(db, profile, business_today())
    ids = list(supervisor.user_ids)
    if supervisor.stand_in is not None:
        ids.append(supervisor.stand_in.user_id)
    return [uid for uid in ids if uid != subject_user_id]


__all__ = [
    "Actor",
    "approval_recipients",
    "is_time_approver",
    "load_actor",
    "users_with_permission",
]
