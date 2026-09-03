"""Authoritative, database-backed product-section access policy.

The matrix in this module bootstraps a fresh database and supports isolated
unit tests. Runtime requests resolve role rows and per-user overrides from
Postgres on every authentication, so an admin change works across all API pods
without a process-local cache.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import IntEnum, StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section_permission import RoleSectionPermission, UserSectionOverride
from app.models.user import User, UserRole


class ProductSection(StrEnum):
    sourcing = "sourcing"
    pipeline = "pipeline"
    delivery = "delivery"
    insights = "insights"
    finance = "finance"
    system_admin = "system_admin"


class SectionAccess(IntEnum):
    none = 0
    read = 1
    write = 2


_NONE = {section: SectionAccess.none for section in ProductSection}


def _policy(**overrides: SectionAccess) -> dict[ProductSection, SectionAccess]:
    policy = dict(_NONE)
    policy.update(
        {ProductSection(section): access for section, access in overrides.items()}
    )
    return policy


# Bootstrap values for migration 0269. Runtime authorization never silently
# falls back to this matrix once a request has been authenticated.
DEFAULT_ROLE_SECTION_ACCESS: dict[UserRole, dict[ProductSection, SectionAccess]] = {
    UserRole.admin: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.write,
        insights=SectionAccess.write,
        finance=SectionAccess.write,
        system_admin=SectionAccess.write,
    ),
    UserRole.finance: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.write,
        insights=SectionAccess.read,
        finance=SectionAccess.write,
    ),
    UserRole.head_of_recruitment: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.write,
    ),
    UserRole.delivery_lead: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.talent_community_manager: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        delivery=SectionAccess.read,
        insights=SectionAccess.read,
    ),
    UserRole.tac: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.recruiter: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.sourcer: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.user: _policy(
        sourcing=SectionAccess.read,
        pipeline=SectionAccess.read,
        insights=SectionAccess.read,
    ),
}

# Backwards-compatible export name. Tests use it as the migration seed contract.
ROLE_SECTION_ACCESS = DEFAULT_ROLE_SECTION_ACCESS


def section_access_for_roles(
    roles: Iterable[UserRole], section: ProductSection
) -> SectionAccess:
    """Return the bootstrap union, used only outside an authenticated request."""

    return max(
        (DEFAULT_ROLE_SECTION_ACCESS.get(role, _NONE)[section] for role in roles),
        default=SectionAccess.none,
    )


def _coerce_access(raw: object) -> SectionAccess:
    if isinstance(raw, SectionAccess):
        return raw
    if isinstance(raw, str):
        try:
            return SectionAccess[raw]
        except KeyError:
            return SectionAccess.none
    if type(raw) is int:
        try:
            return SectionAccess(raw)
        except ValueError:
            return SectionAccess.none
    return SectionAccess.none


def section_access_for_user(user: User, section: ProductSection) -> SectionAccess:
    """Read the resolved request snapshot, failing closed on malformed values.

    Direct service-level unit tests historically pass an unattached ``User``;
    the bootstrap union remains a compatibility path for those callers. Every
    HTTP authentication path attaches ``effective_section_access`` from the
    database before any domain guard executes.
    """

    effective = getattr(user, "effective_section_access", None)
    if isinstance(effective, Mapping):
        return _coerce_access(effective.get(section.value, effective.get(section)))
    return section_access_for_roles(user.get_all_roles(), section)


def serialize_section_access(
    policy: Mapping[ProductSection, SectionAccess],
) -> dict[str, str]:
    return {
        section.value: policy.get(section, SectionAccess.none).name
        for section in ProductSection
    }


def base_policy_from_rows(
    roles: Iterable[UserRole],
    rows: Iterable[RoleSectionPermission],
) -> dict[ProductSection, SectionAccess]:
    """Compute a fail-closed multi-role union from persisted rows."""

    role_values = {role.value for role in roles}
    policy = dict(_NONE)
    for row in rows:
        if row.role not in role_values:
            continue
        try:
            section = ProductSection(row.section)
        except ValueError:
            continue
        policy[section] = max(policy[section], _coerce_access(row.access))
    return policy


def effective_policy_from_rows(
    user: User,
    role_rows: Iterable[RoleSectionPermission],
    override_rows: Iterable[UserSectionOverride],
) -> dict[ProductSection, SectionAccess]:
    """Role union followed by explicit per-user replacement."""

    if user.has_role(UserRole.admin):
        return {section: SectionAccess.write for section in ProductSection}

    policy = base_policy_from_rows(user.get_all_roles(), role_rows)
    for row in override_rows:
        if row.user_id != user.id:
            continue
        try:
            section = ProductSection(row.section)
        except ValueError:
            continue
        policy[section] = _coerce_access(row.access)

    # Technical administration is deliberately not delegable from this panel.
    policy[ProductSection.system_admin] = SectionAccess.none
    return policy


async def resolve_effective_section_access(
    db: AsyncSession, user: User
) -> dict[ProductSection, SectionAccess]:
    """Load and attach the authoritative effective policy for ``user``."""

    await resolve_effective_section_access_for_users(db, [user])
    return {
        section: section_access_for_user(user, section) for section in ProductSection
    }


async def resolve_effective_section_access_for_users(
    db: AsyncSession, users: Iterable[User]
) -> None:
    """Attach effective policies to a fan-out list with two bounded queries."""

    user_list = list(users)
    if not user_list:
        return
    non_admins = [user for user in user_list if not user.has_role(UserRole.admin)]
    role_values = sorted(
        {role.value for user in non_admins for role in user.get_all_roles()}
    )
    user_ids = [user.id for user in non_admins]
    role_rows = list(
        (
            await db.scalars(
                select(RoleSectionPermission).where(
                    RoleSectionPermission.role.in_(role_values or ["__none__"])
                )
            )
        ).all()
    )
    override_rows = list(
        (
            await db.scalars(
                select(UserSectionOverride).where(
                    UserSectionOverride.user_id.in_(user_ids or [-1])
                )
            )
        ).all()
    )
    overrides_by_user: dict[int, list[UserSectionOverride]] = {}
    for row in override_rows:
        overrides_by_user.setdefault(row.user_id, []).append(row)

    for user in user_list:
        policy = (
            {section: SectionAccess.write for section in ProductSection}
            if user.has_role(UserRole.admin)
            else effective_policy_from_rows(
                user, role_rows, overrides_by_user.get(user.id, [])
            )
        )
        user.effective_section_access = serialize_section_access(policy)
