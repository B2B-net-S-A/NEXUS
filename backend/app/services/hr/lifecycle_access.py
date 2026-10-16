"""Kto widzi i odhacza wejście i odejście.

* **Kadry** (``people_admin``) i admin — wszystko: zakładają sprawy, zmieniają
  szablony, wskazują przejmujących, cofają odejście.
* **Przełożony** osoby (z kartoteki albo wskazany w sprawie) — widzi sprawę
  swojego człowieka i odhacza każde jej zadanie.
* **Wykonawca zadania** — widzi sprawę, w której ma zadanie, i odhacza swoje
  zadania. Pule: „Kadry” (uprawnienie Kadry), „recepcja” (uprawnienie Sprzęt),
  „IT” (admini NEXUSA); zadanie „osoba” należy do samej osoby.
* Pozostali — 403.

Powód odejścia widzą wyłącznie Kadry i przełożony (wykonawca dostaje samą
sprawę i zadania).
"""

from __future__ import annotations

from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_lifecycle import LifecycleCase, LifecycleTask
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.action_permissions import ProductAction, has_permission

CaseScope = Literal["admin", "manager", "assignee", "none"]

#: Pule wykonawców bez konkretnej osoby w zadaniu.
POOL_KINDS: frozenset[str] = frozenset({"people_admin", "reception", "it"})


def is_lifecycle_admin(user: User) -> bool:
    return user.has_role(UserRole.admin) or has_permission(
        user, ProductAction.people_admin
    )


def in_pool(user: User, assignee_kind: str) -> bool:
    """Czy konto należy do puli wykonawców zadania bez osoby."""

    if user.has_role(UserRole.admin):
        return True
    if assignee_kind == "people_admin":
        return has_permission(user, ProductAction.people_admin)
    if assignee_kind == "reception":
        return has_permission(user, ProductAction.equipment)
    return False


def owns_task(user: User, task: LifecycleTask) -> bool:
    if task.assignee_user_id is not None:
        return task.assignee_user_id == user.id
    return task.assignee_kind in POOL_KINDS and in_pool(user, task.assignee_kind)


async def is_manager_of_case(db: AsyncSession, user: User, case: LifecycleCase) -> bool:
    if case.manager_user_id is not None and case.manager_user_id == user.id:
        return True
    if case.user_id is None:
        return False
    manager_id = await db.scalar(
        select(EmployeeProfile.manager_user_id).where(
            EmployeeProfile.user_id == case.user_id
        )
    )
    return manager_id is not None and manager_id == user.id


async def case_scope(db: AsyncSession, user: User, case: LifecycleCase) -> CaseScope:
    if is_lifecycle_admin(user):
        return "admin"
    if await is_manager_of_case(db, user, case):
        return "manager"
    tasks = await db.scalars(
        select(LifecycleTask).where(LifecycleTask.case_id == case.id)
    )
    if any(owns_task(user, task) for task in tasks):
        return "assignee"
    return "none"


def can_toggle(scope: CaseScope, user: User, task: LifecycleTask) -> bool:
    if scope in ("admin", "manager"):
        return True
    return scope == "assignee" and owns_task(user, task)


async def pool_member_ids(db: AsyncSession, assignee_kind: str) -> list[int]:
    """Aktywne konta puli (Kadry/recepcja bez adminów; brak puli → admini)."""

    from app.services.effective_access import resolve_effective_access  # noqa: PLC0415

    users = list(await db.scalars(select(User).where(User.is_active.is_(True))))
    admins = [user.id for user in users if user.has_role(UserRole.admin)]
    if assignee_kind == "it":
        return admins
    action: Optional[ProductAction] = {
        "people_admin": ProductAction.people_admin,
        "reception": ProductAction.equipment,
    }.get(assignee_kind)
    if action is None:
        return []
    await resolve_effective_access(db, users)
    holders = [
        user.id
        for user in users
        if not user.has_role(UserRole.admin) and has_permission(user, action)
    ]
    return holders or admins
