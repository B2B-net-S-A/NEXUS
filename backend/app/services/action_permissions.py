"""Database-backed permissions for privileged actions inside product sections.

Section access remains the coarse ceiling. Action access is an additional,
independently configurable gate for workflows that need more nuance than
read/write for a whole section, such as rate-bearing B2B contract documents.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import IntEnum, StrEnum

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.section_permission import RoleActionPermission, UserActionOverride
from app.models.user import User, UserRole


class ProductAction(StrEnum):
    b2b_contract_generator = "b2b_contract_generator"
    b2b_signature_confirmation = "b2b_signature_confirmation"


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


# Preserve the pre-cutover behavior for every role except the intentionally
# read-only TCM persona. The legacy viewer remains view-only because its
# Sourcing section ceiling is also read-only.
DEFAULT_ROLE_ACTION_ACCESS: dict[UserRole, dict[ProductAction, ActionAccess]] = {
    UserRole.admin: _policy(
        b2b_contract_generator=ActionAccess.manage,
        b2b_signature_confirmation=ActionAccess.manage,
    ),
    UserRole.finance: _policy(b2b_contract_generator=ActionAccess.manage),
    UserRole.head_of_recruitment: _policy(b2b_contract_generator=ActionAccess.manage),
    UserRole.delivery_lead: _policy(
        b2b_contract_generator=ActionAccess.manage,
        b2b_signature_confirmation=ActionAccess.manage,
    ),
    UserRole.talent_community_manager: _policy(
        b2b_contract_generator=ActionAccess.view,
        b2b_signature_confirmation=ActionAccess.manage,
    ),
    UserRole.tac: _policy(
        b2b_contract_generator=ActionAccess.manage,
        b2b_signature_confirmation=ActionAccess.manage,
    ),
    UserRole.recruiter: _policy(b2b_contract_generator=ActionAccess.manage),
    UserRole.sourcer: _policy(b2b_contract_generator=ActionAccess.manage),
    UserRole.user: _policy(b2b_contract_generator=ActionAccess.view),
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


def serialize_action_access(
    policy: Mapping[ProductAction, ActionAccess],
) -> dict[str, str]:
    return {
        action.value: policy.get(action, ActionAccess.none).name
        for action in ProductAction
    }


def base_action_policy_from_rows(
    roles: Iterable[UserRole],
    rows: Iterable[RoleActionPermission],
) -> dict[ProductAction, ActionAccess]:
    """Compute a fail-closed multi-role union from persisted rows."""

    role_values = {role.value for role in roles}
    policy = dict(_NONE)
    for row in rows:
        if row.role not in role_values:
            continue
        try:
            action = ProductAction(row.action)
        except ValueError:
            continue
        policy[action] = max(policy[action], _coerce_access(row.access))
    return policy


def effective_action_policy_from_rows(
    user: User,
    role_rows: Iterable[RoleActionPermission],
    override_rows: Iterable[UserActionOverride],
) -> dict[ProductAction, ActionAccess]:
    """Role union followed by explicit per-user replacement."""

    if user.has_role(UserRole.admin):
        return {action: ActionAccess.manage for action in ProductAction}

    policy = base_action_policy_from_rows(user.get_all_roles(), role_rows)
    for row in override_rows:
        if row.user_id != user.id:
            continue
        try:
            action = ProductAction(row.action)
        except ValueError:
            continue
        policy[action] = _coerce_access(row.access)
    return policy


async def resolve_effective_action_access(
    db: AsyncSession, user: User
) -> dict[ProductAction, ActionAccess]:
    """Load and attach the authoritative action policy for one request."""

    if user.has_role(UserRole.admin):
        policy = {action: ActionAccess.manage for action in ProductAction}
    else:
        role_values = sorted(role.value for role in user.get_all_roles())
        role_rows = list(
            (
                await db.scalars(
                    select(RoleActionPermission).where(
                        RoleActionPermission.role.in_(role_values or ["__none__"])
                    )
                )
            ).all()
        )
        override_rows = list(
            (
                await db.scalars(
                    select(UserActionOverride).where(
                        UserActionOverride.user_id == user.id
                    )
                )
            ).all()
        )
        policy = effective_action_policy_from_rows(user, role_rows, override_rows)

    user.effective_action_access = serialize_action_access(policy)
    return policy
