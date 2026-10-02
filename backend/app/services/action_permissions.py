"""Database-backed permissions for privileged actions inside product sections.

Dwa rodzaje akcji w jednym mechanizmie (te same tabele, ten sam audyt):

* ``b2b_contract_generator`` — drabinka podgląd / generowanie / zarządzanie,
* dziewięć uprawnień z ekranu Ustawienia → Osoby i role
  (``permission_catalog``) — tak/nie, zapisane jako ``manage`` / ``none``.

Uprawnienia z ekranu mają zależności (edycja pociąga podgląd) liczone przy
odczycie, a z nich wynikają sekcje Delivery i Finanse
(``section_permissions``). Pytaj o nie przez ``has_permission``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import IntEnum, StrEnum

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section_permission import (
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
)
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog


class ProductAction(StrEnum):
    b2b_contract_generator = "b2b_contract_generator"
    b2b_signature_confirmation = "b2b_signature_confirmation"
    delivery_view = "delivery_view"
    clients_edit = "clients_edit"
    contracts_orders_edit = "contracts_orders_edit"
    contract_status = "contract_status"
    recruitment_manage = "recruitment_manage"
    amounts_view = "amounts_view"
    amounts_edit = "amounts_edit"
    finance_module = "finance_module"


class ActionAccess(IntEnum):
    none = 0
    view = 1
    generate = 2
    manage = 3


_NONE = {action: ActionAccess.none for action in ProductAction}


def _policy(**overrides: ActionAccess) -> dict[ProductAction, ActionAccess]:
    policy = dict(_NONE)
    policy.update(
        {ProductAction(action): access for action, access in overrides.items()}
    )
    return policy


#: Dziewięć uprawnień z ekranu, w kolejności katalogu.
NAMED_PERMISSIONS: tuple[ProductAction, ...] = tuple(
    ProductAction(key) for key in catalog.KEYS
)
_SEEDED_PERMISSIONS = frozenset(ProductAction(key) for key in catalog.SEEDED_KEYS)

# Pełny generator dla każdej roli operacyjnej. TCM ma „manage" od decyzji
# Artura z 22.09.2026 (na produkcji ustawione w panelu RBAC 03–04.09) — seed
# migracji 0273 i lustro w entrypoint.sh nadal zasiewają dla TCM „view", więc
# świeże środowisko wymaga osobnej migracji danych (patrz
# test_action_permissions_migration.SEED_DIVERGENCE_AFTER_0273). Legacy viewer
# zostaje przy podglądzie, bo jego sufit Sourcing też jest tylko do odczytu.
_GENERATOR_DEFAULTS: dict[UserRole, ActionAccess] = {
    UserRole.admin: ActionAccess.manage,
    UserRole.finance: ActionAccess.manage,
    UserRole.head_of_recruitment: ActionAccess.manage,
    UserRole.delivery_lead: ActionAccess.manage,
    UserRole.talent_community_manager: ActionAccess.manage,
    UserRole.tac: ActionAccess.manage,
    UserRole.recruiter: ActionAccess.manage,
    UserRole.sourcer: ActionAccess.manage,
    UserRole.user: ActionAccess.view,
    UserRole.trainee: ActionAccess.none,
}


def _default_policy(role: UserRole) -> dict[ProductAction, ActionAccess]:
    policy = _policy(b2b_contract_generator=_GENERATOR_DEFAULTS[role])
    for key in catalog.default_permissions_for_role(role.value):
        policy[ProductAction(key)] = ActionAccess.manage
    return policy


# Wartości startowe: generator jak wyżej, dziewięć uprawnień według domyślnych
# posiadaczy z katalogu (z zależnościami). Żądanie HTTP czyta wiersze z bazy.
DEFAULT_ROLE_ACTION_ACCESS: dict[UserRole, dict[ProductAction, ActionAccess]] = {
    role: _default_policy(role) for role in UserRole
}


def action_access_for_roles(
    roles: Iterable[UserRole], action: ProductAction
) -> ActionAccess:
    """Return the bootstrap union, used outside authenticated requests."""

    return max(
        (DEFAULT_ROLE_ACTION_ACCESS.get(role, _NONE)[action] for role in roles),
        default=ActionAccess.none,
    )


def _coerce_access(raw: object) -> ActionAccess:
    if isinstance(raw, ActionAccess):
        return raw
    if isinstance(raw, str):
        try:
            return ActionAccess[raw]
        except KeyError:
            return ActionAccess.none
    if type(raw) is int:
        try:
            return ActionAccess(raw)
        except ValueError:
            return ActionAccess.none
    return ActionAccess.none


def action_access_for_user(user: User, action: ProductAction) -> ActionAccess:
    """Read the request-local snapshot and fail closed on malformed values."""

    effective = getattr(user, "effective_action_access", None)
    if isinstance(effective, Mapping):
        return _coerce_access(effective.get(action.value, effective.get(action)))
    return action_access_for_roles(user.get_all_roles(), action)


def has_permission(user: User, permission: ProductAction | str) -> bool:
    """Czy konto ma jedno z dziewięciu uprawnień z ekranu (z zależnościami)."""

    return (
        action_access_for_user(user, ProductAction(permission)) >= ActionAccess.manage
    )


def named_permissions_of(user: User) -> frozenset[str]:
    """Klucze uprawnień z ekranu, które konto ma w tym żądaniu."""

    return frozenset(
        action.value for action in NAMED_PERMISSIONS if has_permission(user, action)
    )


def serialize_action_access(
    policy: Mapping[ProductAction, ActionAccess],
) -> dict[str, str]:
    return {
        action.value: policy.get(action, ActionAccess.none).name
        for action in ProductAction
    }


def close_named_permissions(
    policy: Mapping[ProductAction, ActionAccess],
) -> dict[ProductAction, ActionAccess]:
    """Uprawnienia z ekranu jako tak/nie, razem z tymi, które z nich wynikają."""

    effective = catalog.close(
        action.value
        for action in NAMED_PERMISSIONS
        if policy.get(action, ActionAccess.none) >= ActionAccess.manage
    )
    closed = dict(policy)
    for action in NAMED_PERMISSIONS:
        closed[action] = (
            ActionAccess.manage if action.value in effective else ActionAccess.none
        )
    return closed


def base_action_policy_from_rows(
    roles: Iterable[UserRole],
    rows: Iterable[RoleActionPermission],
    section_rows: Iterable[RoleSectionPermission] = (),
) -> dict[ProductAction, ActionAccess]:
    """Compute a fail-closed multi-role union from persisted rows.

    Rola, która nie ma ŻADNEGO wiersza zasiewanych uprawnień (baza sprzed
    migracji 0410, a siatka przy starcie przegrała zamek), jest liczona
    funkcją zasiewu z jej zapisanych sekcji (``section_rows``) — inaczej taki
    start odebrałby wszystkim Delivery. Rola zasiana częściowo zostaje przy
    tym, co zapisane: brakujący wiersz to „nie”.
    """

    role_values = {role.value for role in roles}
    stored: dict[str, dict[ProductAction, ActionAccess]] = {
        value: {} for value in role_values
    }
    for row in rows:
        if row.role not in role_values:
            continue
        try:
            action = ProductAction(row.action)
        except ValueError:
            continue
        current = stored[row.role].get(action, ActionAccess.none)
        stored[row.role][action] = max(current, _coerce_access(row.access))

    section_levels: dict[str, dict[str, str]] = {}
    for row in section_rows:
        if row.role in role_values:
            section_levels.setdefault(row.role, {})[row.section] = row.access

    policy = dict(_NONE)
    for role_value, role_policy in stored.items():
        if _SEEDED_PERMISSIONS.isdisjoint(role_policy):
            seeded = catalog.seed_rows_for_role(
                role_value, section_levels.get(role_value, {})
            )
            for key, access in seeded.items():
                role_policy[ProductAction(key)] = _coerce_access(access)
        for action, access in role_policy.items():
            policy[action] = max(policy[action], access)
    return policy


def effective_action_policy_from_rows(
    user: User,
    role_rows: Iterable[RoleActionPermission],
    override_rows: Iterable[UserActionOverride],
    section_rows: Iterable[RoleSectionPermission] = (),
) -> dict[ProductAction, ActionAccess]:
    """Role union, explicit per-user replacement, then permission closure."""

    if user.has_role(UserRole.admin):
        return {action: ActionAccess.manage for action in ProductAction}

    policy = base_action_policy_from_rows(user.get_all_roles(), role_rows, section_rows)
    for row in override_rows:
        if row.user_id != user.id:
            continue
        try:
            action = ProductAction(row.action)
        except ValueError:
            continue
        policy[action] = _coerce_access(row.access)
    return close_named_permissions(policy)


async def resolve_effective_action_access(
    db: AsyncSession, user: User
) -> dict[ProductAction, ActionAccess]:
    """Load and attach the authoritative policy (sections and actions)."""

    from app.services.effective_access import resolve_effective_access

    await resolve_effective_access(db, [user])
    return {action: action_access_for_user(user, action) for action in ProductAction}
