"""Admin-only API for role section policy and per-user exceptions."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.section_permission import (
    RbacPermissionAudit,
    RbacPolicyState,
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services.action_permissions import (
    ActionAccess,
    ProductAction,
    base_action_policy_from_rows,
    effective_action_policy_from_rows,
    serialize_action_access,
)
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    base_policy_from_rows,
    effective_policy_from_rows,
    serialize_section_access,
)


router = APIRouter()

AccessName = Literal["none", "read", "write"]
OverrideName = Literal["inherit", "none", "read", "write"]
ActionAccessName = Literal["none", "view", "generate", "manage"]
ActionOverrideName = Literal["inherit", "none", "view", "generate", "manage"]


class RolePermissionChange(BaseModel):
    role: UserRole
    section: ProductSection
    access: AccessName


class RoleActionPermissionChange(BaseModel):
    role: UserRole
    action: ProductAction
    access: ActionAccessName


class RolePermissionUpdate(BaseModel):
    revision: int = Field(..., ge=1)
    changes: list[RolePermissionChange] = Field(default_factory=list, max_length=54)
    action_changes: list[RoleActionPermissionChange] = Field(
        default_factory=list, max_length=9
    )


class UserPermissionChange(BaseModel):
    section: ProductSection
    access: OverrideName


class UserActionPermissionChange(BaseModel):
    action: ProductAction
    access: ActionOverrideName


class UserPermissionUpdate(BaseModel):
    revision: int = Field(..., ge=1)
    changes: list[UserPermissionChange] = Field(default_factory=list, max_length=6)
    action_changes: list[UserActionPermissionChange] = Field(
        default_factory=list, max_length=1
    )


async def _policy_state(db: AsyncSession, *, lock: bool = False) -> RbacPolicyState:
    statement = select(RbacPolicyState).where(RbacPolicyState.id == 1)
    if lock:
        statement = statement.with_for_update()
    state_row = await db.scalar(statement)
    if state_row is None:
        # Never reconstruct policy from code in a live request. Missing
        # bootstrap data is an operational fault and must fail closed.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "section_policy_unavailable"},
        )
    return state_row


async def _revalidate_locked_admin(db: AsyncSession, admin: User) -> User:
    """Linearize a policy mutation with concurrent role/status changes."""

    locked_admin = await db.scalar(
        select(User)
        .where(User.id == admin.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        locked_admin is None
        or not locked_admin.is_active
        or not locked_admin.has_role(UserRole.admin)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "administrator_access_changed"},
        )
    return locked_admin


def _assert_unique(items: list[tuple[str, str]]) -> None:
    if len(items) != len(set(items)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "duplicate_permission_change"},
        )


def _assert_revision(state_row: RbacPolicyState, expected: int) -> None:
    if state_row.revision != expected:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "stale_section_policy",
                "expected_revision": expected,
                "current_revision": state_row.revision,
            },
        )


def _role_payload(
    role: UserRole,
    section_rows: list[RoleSectionPermission],
    action_rows: list[RoleActionPermission],
) -> dict[str, object]:
    if role is UserRole.admin:
        permissions = {
            section.value: SectionAccess.write.name for section in ProductSection
        }
        action_permissions = {
            action.value: ActionAccess.manage.name for action in ProductAction
        }
    else:
        permissions = serialize_section_access(
            base_policy_from_rows([role], section_rows)
        )
        permissions[ProductSection.system_admin.value] = SectionAccess.none.name
        action_permissions = serialize_action_access(
            base_action_policy_from_rows([role], action_rows)
        )
    return {
        "role": role.value,
        "permissions": permissions,
        "action_permissions": action_permissions,
        "locked": role is UserRole.admin,
        "locked_sections": [ProductSection.system_admin.value],
    }


async def _role_snapshot(db: AsyncSession) -> dict[str, object]:
    state_row = await _policy_state(db)
    section_rows = list((await db.scalars(select(RoleSectionPermission))).all())
    action_rows = list((await db.scalars(select(RoleActionPermission))).all())
    return {
        "revision": state_row.revision,
        "sections": [section.value for section in ProductSection],
        "actions": [action.value for action in ProductAction],
        "roles": [_role_payload(role, section_rows, action_rows) for role in UserRole],
        "updated_at": state_row.updated_at,
        "updated_by": state_row.updated_by,
    }


@router.get("")
async def read_role_section_permissions(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Return the complete fail-closed role matrix and global revision."""

    return await _role_snapshot(db)


@router.get("/users")
async def read_user_section_permissions(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=250),
):
    """Return accounts with inherited, overridden and effective access."""

    state_row = await _policy_state(db)
    query = select(User).order_by(User.is_active.desc(), User.name, User.id)
    count_query = select(func.count(User.id))
    needle = search.strip()
    if needle:
        predicate = or_(
            User.name.ilike(f"%{needle}%"),
            User.email.ilike(f"%{needle}%"),
        )
        query = query.where(predicate)
        count_query = count_query.where(predicate)
    users = list((await db.scalars(query.limit(limit))).all())
    total = int((await db.scalar(count_query)) or 0)
    role_rows = list((await db.scalars(select(RoleSectionPermission))).all())
    action_role_rows = list((await db.scalars(select(RoleActionPermission))).all())
    user_ids = [user.id for user in users]
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
    for override in override_rows:
        overrides_by_user.setdefault(override.user_id, []).append(override)
    action_override_rows = list(
        (
            await db.scalars(
                select(UserActionOverride).where(
                    UserActionOverride.user_id.in_(user_ids or [-1])
                )
            )
        ).all()
    )
    action_overrides_by_user: dict[int, list[UserActionOverride]] = {}
    for override in action_override_rows:
        action_overrides_by_user.setdefault(override.user_id, []).append(override)

    payload_users: list[dict[str, object]] = []
    for user in users:
        user_overrides = overrides_by_user.get(user.id, [])
        user_action_overrides = action_overrides_by_user.get(user.id, [])
        inherited = (
            {section: SectionAccess.write for section in ProductSection}
            if user.has_role(UserRole.admin)
            else base_policy_from_rows(user.get_all_roles(), role_rows)
        )
        if not user.has_role(UserRole.admin):
            inherited[ProductSection.system_admin] = SectionAccess.none
        effective = effective_policy_from_rows(user, role_rows, user_overrides)
        inherited_actions = (
            {action: ActionAccess.manage for action in ProductAction}
            if user.has_role(UserRole.admin)
            else base_action_policy_from_rows(user.get_all_roles(), action_role_rows)
        )
        effective_actions = effective_action_policy_from_rows(
            user, action_role_rows, user_action_overrides
        )
        payload_users.append(
            {
                "user_id": user.id,
                "name": user.name,
                "email": user.email,
                "role": user.role.value,
                "roles": sorted(role.value for role in user.get_all_roles()),
                "is_active": user.is_active,
                "locked": user.has_role(UserRole.admin),
                "overrides": {row.section: row.access for row in user_overrides},
                "inherited_permissions": serialize_section_access(inherited),
                "effective_permissions": serialize_section_access(effective),
                "action_overrides": {
                    row.action: row.access for row in user_action_overrides
                },
                "inherited_action_permissions": serialize_action_access(
                    inherited_actions
                ),
                "effective_action_permissions": serialize_action_access(
                    effective_actions
                ),
                "scope_summary": (
                    "Tylko przypisani klienci"
                    if user.has_role(UserRole.delivery_lead)
                    and not user.has_any_role(UserRole.admin, UserRole.finance)
                    else "Zakres danych nadal wynika z roli i przypisań"
                ),
            }
        )

    return {"revision": state_row.revision, "users": payload_users, "total": total}


@router.put("/roles")
async def update_role_section_permissions(
    payload: RolePermissionUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Atomically apply section/action changes and revoke affected sessions."""

    if not payload.changes and not payload.action_changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_permission_change"},
        )
    _assert_unique(
        [
            (change.role.value, f"section:{change.section.value}")
            for change in payload.changes
        ]
        + [
            (change.role.value, f"action:{change.action.value}")
            for change in payload.action_changes
        ]
    )
    for change in payload.changes:
        if (
            change.role is UserRole.admin
            or change.section is ProductSection.system_admin
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "immutable_technical_admin_access"},
            )
    if any(change.role is UserRole.admin for change in payload.action_changes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "immutable_admin_access"},
        )

    state_row = await _policy_state(db, lock=True)
    admin = await _revalidate_locked_admin(db, admin)
    _assert_revision(state_row, payload.revision)
    requested_roles = sorted(
        {change.role.value for change in payload.changes}
        | {change.role.value for change in payload.action_changes}
    )
    existing_rows = list(
        (
            await db.scalars(
                select(RoleSectionPermission)
                .where(RoleSectionPermission.role.in_(requested_roles))
                .with_for_update()
            )
        ).all()
    )
    by_key = {(row.role, row.section): row for row in existing_rows}
    existing_action_rows = list(
        (
            await db.scalars(
                select(RoleActionPermission)
                .where(RoleActionPermission.role.in_(requested_roles))
                .with_for_update()
            )
        ).all()
    )
    action_by_key = {(row.role, row.action): row for row in existing_action_rows}
    before: dict[str, str] = {}
    after: dict[str, str] = {}
    changed_roles: set[str] = set()
    now = datetime.now(timezone.utc)

    for change in payload.changes:
        key = (change.role.value, change.section.value)
        row = by_key.get(key)
        old_access = row.access if row is not None else SectionAccess.none.name
        before[f"{key[0]}:{key[1]}"] = row.access if row is not None else "missing"
        after[f"{key[0]}:{key[1]}"] = change.access
        # A missing row resolves to ``none`` at runtime, but it must still be
        # materialized when an administrator explicitly saves ``none``.
        # This repairs the matrix without treating absence as a silent no-op.
        if row is not None and old_access == change.access:
            continue
        changed_roles.add(change.role.value)
        if row is None:
            row = RoleSectionPermission(
                role=change.role.value,
                section=change.section.value,
                access=change.access,
            )
            db.add(row)
            by_key[key] = row
        else:
            row.access = change.access
        row.updated_by = admin.id
        row.updated_at = now

    for change in payload.action_changes:
        key = (change.role.value, change.action.value)
        row = action_by_key.get(key)
        old_access = row.access if row is not None else ActionAccess.none.name
        audit_key = f"{key[0]}:action:{key[1]}"
        before[audit_key] = row.access if row is not None else "missing"
        after[audit_key] = change.access
        if row is not None and old_access == change.access:
            continue
        changed_roles.add(change.role.value)
        if row is None:
            row = RoleActionPermission(
                role=change.role.value,
                action=change.action.value,
                access=change.access,
            )
            db.add(row)
            action_by_key[key] = row
        else:
            row.access = change.access
        row.updated_by = admin.id
        row.updated_at = now

    if not changed_roles:
        return {
            "revision": state_row.revision,
            "changed": False,
            "invalidated_users": 0,
        }

    next_revision = state_row.revision + 1
    state_row.revision = next_revision
    state_row.updated_by = admin.id
    state_row.updated_at = now

    role_conditions = []
    for role_value in changed_roles:
        role_enum = UserRole(role_value)
        role_conditions.extend(
            [User.role == role_enum, User.roles.contains([role_value])]
        )
    invalidation = await db.execute(
        update(User)
        .where(User.is_active.is_(True), or_(*role_conditions))
        .values(
            authorization_version=User.authorization_version + 1,
            tokens_valid_after=now,
        )
        .execution_options(synchronize_session=False)
    )
    invalidated_users = int(getattr(invalidation, "rowcount", 0) or 0)
    db.add(
        RbacPermissionAudit(
            actor_user_id=admin.id,
            target_kind="role",
            target_key=",".join(sorted(changed_roles)),
            revision=next_revision,
            before=before,
            after=after,
        )
    )
    await db.flush()
    return {
        "revision": next_revision,
        "changed": True,
        "invalidated_users": invalidated_users,
    }


@router.put("/users/{user_id}")
async def update_user_section_permissions(
    user_id: int,
    payload: UserPermissionUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Replace selected user overrides; ``inherit`` removes the stored row."""

    if not payload.changes and not payload.action_changes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_permission_change"},
        )
    _assert_unique(
        [
            (str(user_id), f"section:{change.section.value}")
            for change in payload.changes
        ]
        + [
            (str(user_id), f"action:{change.action.value}")
            for change in payload.action_changes
        ]
    )
    if any(change.section is ProductSection.system_admin for change in payload.changes):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "immutable_technical_admin_access"},
        )

    state_row = await _policy_state(db, lock=True)
    admin = await _revalidate_locked_admin(db, admin)
    _assert_revision(state_row, payload.revision)
    target = await db.scalar(select(User).where(User.id == user_id).with_for_update())
    if target is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if target.has_role(UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "immutable_admin_access"},
        )

    rows = list(
        (
            await db.scalars(
                select(UserSectionOverride)
                .where(UserSectionOverride.user_id == user_id)
                .with_for_update()
            )
        ).all()
    )
    by_section = {row.section: row for row in rows}
    action_rows = list(
        (
            await db.scalars(
                select(UserActionOverride)
                .where(UserActionOverride.user_id == user_id)
                .with_for_update()
            )
        ).all()
    )
    by_action = {row.action: row for row in action_rows}
    before = {row.section: row.access for row in rows}
    before.update({f"action:{row.action}": row.access for row in action_rows})
    now = datetime.now(timezone.utc)
    changed = False
    for change in payload.changes:
        section = change.section.value
        row = by_section.get(section)
        if change.access == "inherit":
            if row is not None:
                await db.delete(row)
                by_section.pop(section)
                changed = True
            continue
        if row is None:
            row = UserSectionOverride(
                user_id=user_id,
                section=section,
                access=change.access,
                updated_by=admin.id,
                updated_at=now,
            )
            db.add(row)
            by_section[section] = row
            changed = True
        elif row.access != change.access:
            row.access = change.access
            row.updated_by = admin.id
            row.updated_at = now
            changed = True

    for change in payload.action_changes:
        action = change.action.value
        row = by_action.get(action)
        if change.access == "inherit":
            if row is not None:
                await db.delete(row)
                by_action.pop(action)
                changed = True
            continue
        if row is None:
            row = UserActionOverride(
                user_id=user_id,
                action=action,
                access=change.access,
                updated_by=admin.id,
                updated_at=now,
            )
            db.add(row)
            by_action[action] = row
            changed = True
        elif row.access != change.access:
            row.access = change.access
            row.updated_by = admin.id
            row.updated_at = now
            changed = True

    if not changed:
        return {
            "revision": state_row.revision,
            "changed": False,
            "invalidated_users": 0,
        }

    next_revision = state_row.revision + 1
    state_row.revision = next_revision
    state_row.updated_by = admin.id
    state_row.updated_at = now
    target.authorization_version += 1
    target.tokens_valid_after = now
    after = {section: row.access for section, row in sorted(by_section.items())}
    after.update(
        {f"action:{action}": row.access for action, row in sorted(by_action.items())}
    )
    db.add(
        RbacPermissionAudit(
            actor_user_id=admin.id,
            target_kind="user",
            target_key=str(user_id),
            revision=next_revision,
            before=before,
            after=after,
        )
    )
    await db.flush()
    return {"revision": next_revision, "changed": True, "invalidated_users": 1}
