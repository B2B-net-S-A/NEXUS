"""Authoritative, database-backed product-section access policy.

The matrix in this module bootstraps a fresh database and supports isolated
unit tests. Runtime requests resolve role rows and per-user overrides from
Postgres on every authentication, so an admin change works across all API pods
without a process-local cache.

Od migracji 0410 sekcje **Delivery i Finanse nie są ustawiane ręcznie**:
wynikają z dziewięciu uprawnień z ekranu (``permission_catalog.derive_sections``).
Zapisane wiersze tych dwóch sekcji zostają w bazie (powrót do poprzedniej
wersji, progi zasiewu), ale resolver ich nie czyta. Sourcing, Pipeline,
Insights i System działają jak dotąd.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import IntEnum, StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section_permission import RoleSectionPermission, UserSectionOverride
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog


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

#: Sekcje wyliczane z uprawnień z ekranu zamiast z zapisanych wierszy.
DERIVED_SECTIONS: frozenset[ProductSection] = frozenset(
    {ProductSection.delivery, ProductSection.finance}
)


def derived_section_access(
    permissions: Iterable[str],
) -> dict[ProductSection, SectionAccess]:
    """Poziom Delivery i Finansów wynikający z posiadanych uprawnień."""

    return {
        ProductSection(section): SectionAccess[access]
        for section, access in catalog.derive_sections(permissions).items()
    }


def _policy(**overrides: SectionAccess) -> dict[ProductSection, SectionAccess]:
    policy = dict(_NONE)
    policy.update(
        {ProductSection(section): access for section, access in overrides.items()}
    )
    return policy


# Bootstrap values for migration 0269. Runtime authorization never silently
# falls back to this matrix once a request has been authenticated.
# Wpisy Delivery i Finanse to historyczny zasiew — służą już tylko jako progi
# zasiewu uprawnień (``permission_catalog.seed_rows_for_role``).
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
    UserRole.recruiter: _policy(
        sourcing=SectionAccess.write,
        pipeline=SectionAccess.write,
        insights=SectionAccess.read,
    ),
    UserRole.user: _policy(
        sourcing=SectionAccess.read,
        pipeline=SectionAccess.read,
        insights=SectionAccess.read,
    ),
    # 0374: praktykant nie ma żadnej sekcji — jego ekran stoi poza sekcjami
    # (`/api/trainee/*`, ``TraineeUser``).
    UserRole.trainee: _policy(),
}

# Backwards-compatible export name. Tests use it as the migration seed contract.
ROLE_SECTION_ACCESS = DEFAULT_ROLE_SECTION_ACCESS


def section_access_for_roles(
    roles: Iterable[UserRole], section: ProductSection
) -> SectionAccess:
    """Return the bootstrap union, used only outside an authenticated request."""

    if section in DERIVED_SECTIONS:
        held: set[str] = set()
        for role in roles:
            held |= catalog.default_permissions_for_role(role.value)
        return derived_section_access(held)[section]
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
    *,
    permissions: Iterable[str] = (),
) -> dict[ProductSection, SectionAccess]:
    """Role union, per-user replacement, then Delivery/Finance from permissions.

    ``permissions`` to uprawnienia z ekranu, które konto ma PO domknięciu
    zależności. Bez nich Delivery i Finanse są zamknięte — zapisane wiersze
    tych sekcji nie nadają już dostępu. Stary wyjątek osoby dla Delivery albo
    Finansów działa wyłącznie jako ograniczenie (nigdy nie podnosi poziomu).
    """

    if user.has_role(UserRole.admin):
        return {section: SectionAccess.write for section in ProductSection}

    policy = base_policy_from_rows(user.get_all_roles(), role_rows)
    policy.update(derived_section_access(permissions))
    for row in override_rows:
        if row.user_id != user.id:
            continue
        try:
            section = ProductSection(row.section)
        except ValueError:
            continue
        access = _coerce_access(row.access)
        if section in DERIVED_SECTIONS:
            access = min(policy[section], access)
        policy[section] = access

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
    """Attach effective policies (sections and actions) to a fan-out list.

    Sekcje Delivery i Finanse wynikają z uprawnień, więc sekcji nie da się
    policzyć bez akcji — jedno wejście ładuje jedno i drugie
    (``effective_access.resolve_effective_access``, cztery ograniczone zapytania).
    """

    from app.services.effective_access import resolve_effective_access

    await resolve_effective_access(db, users)
