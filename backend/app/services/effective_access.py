"""Jedno wejście po politykę dostępu konta: sekcje i uprawnienia razem.

Sekcje Delivery i Finanse wynikają z dziewięciu uprawnień z ekranu, więc
polityki sekcji nie da się policzyć bez polityki akcji. Ten moduł ładuje obie
(cztery ograniczone zapytania, bez pamięci procesu — zmiana w panelu działa od
następnego żądania na każdym workerze) i dołącza do kont ``effective_section_access``
oraz ``effective_action_access``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section_permission import (
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services.action_permissions import (
    NAMED_PERMISSIONS,
    ActionAccess,
    ProductAction,
    effective_action_policy_from_rows,
    serialize_action_access,
)
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    effective_policy_from_rows,
    serialize_section_access,
)


@dataclass(frozen=True)
class EffectiveAccess:
    sections: dict[ProductSection, SectionAccess]
    actions: dict[ProductAction, ActionAccess]

    @property
    def permissions(self) -> frozenset[str]:
        """Klucze uprawnień z ekranu, które konto ma (z zależnościami)."""

        return frozenset(
            action.value
            for action in NAMED_PERMISSIONS
            if self.actions.get(action, ActionAccess.none) >= ActionAccess.manage
        )


def effective_access_from_rows(
    user: User,
    *,
    section_role_rows: Iterable[RoleSectionPermission],
    section_override_rows: Iterable[UserSectionOverride],
    action_role_rows: Iterable[RoleActionPermission],
    action_override_rows: Iterable[UserActionOverride],
) -> EffectiveAccess:
    """Czysta wersja resolvera: te same reguły co żądanie HTTP, bez bazy."""

    section_role_rows = list(section_role_rows)
    actions = effective_action_policy_from_rows(
        user, action_role_rows, action_override_rows, section_role_rows
    )
    permissions = [
        action.value
        for action in NAMED_PERMISSIONS
        if actions[action] >= ActionAccess.manage
    ]
    sections = effective_policy_from_rows(
        user, section_role_rows, section_override_rows, permissions=permissions
    )
    return EffectiveAccess(sections=sections, actions=actions)


def granted_beyond_roles(
    user: User,
    *,
    section_role_rows: Iterable[RoleSectionPermission],
    action_role_rows: Iterable[RoleActionPermission],
    action_override_rows: Iterable[UserActionOverride],
) -> tuple[str, ...]:
    """Uprawnienia nadane OSOBIE, których nie dają jej role (kolejność katalogu).

    Liczy się nadanie zapisane przy osobie. Uprawnienie, które tylko wynika
    z nadanego (podgląd przy edycji), nie jest osobną pozycją — plakietka
    „+1 uprawnienie” ma mówić, ile rzeczy admin tej osobie zaznaczył.
    """

    if user.has_role(UserRole.admin):
        return ()
    granted = {
        row.action
        for row in action_override_rows
        if row.user_id == user.id and row.access == ActionAccess.manage.name
    }
    if not granted:
        return ()
    from_roles = effective_access_from_rows(
        user,
        section_role_rows=section_role_rows,
        section_override_rows=(),
        action_role_rows=action_role_rows,
        action_override_rows=(),
    ).permissions
    return tuple(
        action.value
        for action in NAMED_PERMISSIONS
        if action.value in granted and action.value not in from_roles
    )


async def resolve_effective_access(db: AsyncSession, users: Iterable[User]) -> None:
    """Dołącz bieżącą politykę (sekcje i akcje) do każdego konta z listy."""

    user_list = list(users)
    if not user_list:
        return
    non_admins = [user for user in user_list if not user.has_role(UserRole.admin)]
    role_values = sorted(
        {role.value for user in non_admins for role in user.get_all_roles()}
    ) or ["__none__"]
    user_ids = [user.id for user in non_admins] or [-1]

    section_role_rows = list(
        (
            await db.scalars(
                select(RoleSectionPermission).where(
                    RoleSectionPermission.role.in_(role_values)
                )
            )
        ).all()
    )
    section_override_rows = list(
        (
            await db.scalars(
                select(UserSectionOverride).where(
                    UserSectionOverride.user_id.in_(user_ids)
                )
            )
        ).all()
    )
    action_role_rows = list(
        (
            await db.scalars(
                select(RoleActionPermission).where(
                    RoleActionPermission.role.in_(role_values)
                )
            )
        ).all()
    )
    action_override_rows = list(
        (
            await db.scalars(
                select(UserActionOverride).where(
                    UserActionOverride.user_id.in_(user_ids)
                )
            )
        ).all()
    )

    section_overrides: dict[int, list[UserSectionOverride]] = {}
    for row in section_override_rows:
        section_overrides.setdefault(row.user_id, []).append(row)
    action_overrides: dict[int, list[UserActionOverride]] = {}
    for row in action_override_rows:
        action_overrides.setdefault(row.user_id, []).append(row)

    for user in user_list:
        access = effective_access_from_rows(
            user,
            section_role_rows=section_role_rows,
            section_override_rows=section_overrides.get(user.id, []),
            action_role_rows=action_role_rows,
            action_override_rows=action_overrides.get(user.id, []),
        )
        user.effective_section_access = serialize_section_access(access.sections)
        user.effective_action_access = serialize_action_access(access.actions)
