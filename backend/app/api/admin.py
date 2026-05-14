"""Admin-only API endpoints for user management and system stats."""

import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.user import User, UserRole
from app.models.user_activity import UserActivity
from app.api.deps import AdminUser
from app.schemas.user import UserResponse
from app.services.email import (
    send_password_changed_notification,
    send_password_reset_email,
)
from app.services.password_reset import (
    RESET_TOKEN_TTL_MINUTES,
    create_reset_token,
)

router = APIRouter()

# Roles that must complete first-login onboarding before the frontend unlocks
# the shell. Keep in sync with backend/app/api/onboarding.py.
_ONBOARDING_REQUIRED_ROLES = {UserRole.delivery_lead, UserRole.recruiter}

# ── Schemas ──────────────────────────────────────────────────────────────────


class AdminUserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: UserRole
    is_active: bool
    activity_count: int
    last_activity: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AdminUserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: UserRole = UserRole.recruiter


class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class ResetPasswordRequest(BaseModel):
    new_password: str


# ── Startup time (for uptime calculation) ────────────────────────────────────
_start_time = time.time()


# ── Endpoints ─────────────────────────────────────────────────────────────────


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """List all users with activity counts and last activity timestamp."""
    # Get all users
    users_result = await db.execute(select(User).order_by(User.id))
    users = users_result.scalars().all()

    # Get activity counts per user
    activity_result = await db.execute(
        select(
            UserActivity.user_id,
            func.count(UserActivity.id).label("activity_count"),
            func.max(UserActivity.created_at).label("last_activity"),
        ).group_by(UserActivity.user_id)
    )
    activity_map = {
        row.user_id: {"count": row.activity_count, "last": row.last_activity}
        for row in activity_result.all()
    }

    return [
        AdminUserResponse(
            id=u.id,
            email=u.email,
            name=u.name,
            role=u.role,
            is_active=u.is_active,
            activity_count=activity_map.get(u.id, {}).get("count", 0),
            last_activity=activity_map.get(u.id, {}).get("last"),
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: AdminUserCreate,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Create a new user (admin only)."""
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    preexempt = data.role not in _ONBOARDING_REQUIRED_ROLES
    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        profile_completed=preexempt,
        profile_completed_at=func.now() if preexempt else None,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Update user details (name, role, is_active).

    Security: writes Activity rows for role changes, deactivations and
    name changes so admin actions are auditable. Reset-password already
    logs separately. RODO accountability requires an audit trail for any
    privilege escalation or account state change.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Capture pre-change state for audit log
    original_role = user.role
    original_active = user.is_active
    original_name = user.name

    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.is_active is not None:
        user.is_active = data.is_active

    # Audit: write one Activity per attribute that actually changed
    if data.role is not None and data.role != original_role:
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="role_changed",
                user_id=_admin.id,
                details={
                    "from": original_role.value
                    if hasattr(original_role, "value")
                    else str(original_role),
                    "to": data.role.value
                    if hasattr(data.role, "value")
                    else str(data.role),
                    "target_email": user.email,
                },
            )
        )
    if data.is_active is not None and data.is_active != original_active:
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="active_changed",
                user_id=_admin.id,
                details={
                    "from": original_active,
                    "to": data.is_active,
                    "target_email": user.email,
                },
            )
        )
    if data.name is not None and data.name != original_name:
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="name_changed",
                user_id=_admin.id,
                details={
                    "from": original_name,
                    "to": data.name,
                    "target_email": user.email,
                },
            )
        )

    await db.flush()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete user by setting is_active=False.

    Security: writes Activity row for the soft-delete so the action is
    auditable. RODO accountability + incident response require knowing
    who deactivated whom and when.
    """
    if admin.id == user_id:
        raise HTTPException(
            status_code=400, detail="Cannot deactivate your own account"
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="user_deactivated",
            user_id=admin.id,
            details={"target_email": user.email},
        )
    )
    await db.flush()


@router.post("/users/{user_id}/reset-password", response_model=dict)
async def reset_password(
    user_id: int,
    data: ResetPasswordRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password manually (admin only).

    Po resecie:
    - Ustawiamy ``force_password_change=True`` — user musi przy pierwszym
      loginie zmienić hasło na własne (bo admin zna to tymczasowe).
    - Audit log: ``Activity(action="password_changed_by_admin")``.
    - In-app notification + email do usera (security audit trail).
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(data.new_password)
    user.force_password_change = True
    user.force_password_change_at = func.now()

    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="password_changed_by_admin",
            user_id=_admin.id,
            details={
                "admin_id": _admin.id,
                "admin_email": _admin.email,
                "method": "manual",
            },
        )
    )
    db.add(
        Notification(
            user_id=user.id,
            title="Twoje hasło zostało zresetowane",
            message=(
                f"Administrator {_admin.name} zresetował Twoje hasło. "
                "Przy następnym logowaniu zostaniesz poproszony(-a) o "
                "ustawienie nowego hasła."
            ),
            link="/profile",
            notification_type=NotificationType.password_changed_by_admin,
            related_entity_type="user",
            related_entity_id=user.id,
        )
    )
    await db.flush()

    send_password_changed_notification(
        to_email=user.email,
        recipient_name=user.name,
        by_admin=True,
        admin_name=_admin.name,
    )
    return {"detail": "Password reset successfully"}


@router.post("/users/{user_id}/send-reset-link", response_model=dict)
async def send_reset_link(
    user_id: int,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Send a password reset link to a user via email (admin only).

    Alternatywa dla manual ``reset-password`` — admin nie zna tymczasowego
    hasła, user sam ustawia nowe przez link w mailu (TTL 60 min). Token
    jest jednorazowy. Flag ``force_password_change`` NIE jest ustawiany,
    bo user i tak ustawi własne hasło w reset-password flow.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not user.is_active:
        raise HTTPException(
            status_code=400, detail="Cannot send reset link to deactivated user"
        )

    plain_token = await create_reset_token(db, user.id, requested_by_admin_id=_admin.id)
    base = (settings.PUBLIC_BASE_URL or "").rstrip("/")
    reset_url = f"{base}/login/reset?token={plain_token}"

    send_password_reset_email(
        to_email=user.email,
        recipient_name=user.name,
        reset_url=reset_url,
        expires_minutes=RESET_TOKEN_TTL_MINUTES,
    )

    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action="password_reset_link_sent_by_admin",
            user_id=_admin.id,
            details={
                "admin_id": _admin.id,
                "admin_email": _admin.email,
            },
        )
    )
    db.add(
        Notification(
            user_id=user.id,
            title="Wysłano link do resetu hasła",
            message=(
                f"Administrator {_admin.name} wysłał Ci link do zresetowania "
                "hasła. Sprawdź skrzynkę email — link jest ważny przez 60 minut."
            ),
            link=None,
            notification_type=NotificationType.password_reset_requested,
            related_entity_type="user",
            related_entity_id=user.id,
        )
    )
    await db.flush()
    return {"detail": "Reset link sent to user's email"}


@router.get("/system")
async def system_stats(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """System stats: DB size, entity counts, uptime."""
    candidates_total = (await db.execute(select(func.count(Candidate.id)))).scalar()
    jobs_total = (await db.execute(select(func.count(Job.id)))).scalar()
    clients_total = (await db.execute(select(func.count(Client.id)))).scalar()
    contracts_total = (await db.execute(select(func.count(Contract.id)))).scalar()
    users_total = (await db.execute(select(func.count(User.id)))).scalar()

    # DB size (PostgreSQL)
    try:
        db_size_result = await db.execute(
            text("SELECT pg_size_pretty(pg_database_size(current_database())) AS size")
        )
        db_size = db_size_result.scalar()
    except Exception:
        db_size = "N/A"

    # DB name
    try:
        db_name_result = await db.execute(text("SELECT current_database()"))
        db_name = db_name_result.scalar()
    except Exception:
        db_name = "unknown"

    uptime_seconds = int(time.time() - _start_time)
    hours, remainder = divmod(uptime_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"

    return {
        "counts": {
            "candidates": candidates_total,
            "jobs": jobs_total,
            "clients": clients_total,
            "contracts": contracts_total,
            "users": users_total,
        },
        "database": {
            "name": db_name,
            "size": db_size,
        },
        "uptime": uptime_str,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


# ── AAD group-based RBAC (Phase 7.2) ─────────────────────────────────────────


class ResyncAadGroupsResponse(BaseModel):
    """Result of re-evaluating a user's stored AAD groups against the current
    ``AAD_GROUP_ROLE_MAP_JSON``. No Graph call is made — this only re-runs the
    in-memory mapping. For a fresh fetch the user must log in again.
    """

    user_id: int
    email: str
    aad_group_ids: list[dict]
    previous_role: str
    new_role: str
    role_changed: bool
    is_active: bool


@router.post(
    "/users/{user_id}/resync-aad-groups",
    response_model=ResyncAadGroupsResponse,
)
async def resync_aad_groups(
    user_id: int,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Re-evaluate stored AAD groups against the current role mapping.

    Used when ``AAD_GROUP_ROLE_MAP_JSON`` changes after a user has logged in:
    instead of asking every affected user to log out and back in, the admin
    re-applies the mapping to their already-stored ``aad_group_ids``.

    NOTE: This does NOT call Microsoft Graph — it only re-runs the in-memory
    role mapping against the snapshot saved at the user's last SSO login.
    For a fresh fetch of AAD group membership the user must log in again
    (Phase 7.2 chose this over app-permissions Graph access to avoid the
    extra admin consent surface).

    Behaviour:
        * 422 if RBAC is disabled (``AAD_GROUP_RBAC_ENABLED=false``) —
          calling this endpoint with the feature off would silently no-op.
        * 422 if the user has no stored ``aad_group_ids`` (legacy user or
          never logged in via SSO since 7.2 rollout) — the admin should
          first ask them to re-login.
        * 403 (via Activity log) if no AAD group matches — flips
          ``is_active`` to False, same as SSO callback's denial path.
        * 200 with the new role + ``role_changed`` flag on success.
    """
    if not settings.AAD_GROUP_RBAC_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "AAD group-based RBAC is disabled (AAD_GROUP_RBAC_ENABLED=false). "
                "Enable it in Coolify env vault before calling this endpoint."
            ),
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    stored_groups = user.aad_group_ids or []
    if not stored_groups:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "User has no stored AAD groups. Ask them to log in via "
                "Microsoft SSO once to populate the snapshot, then retry."
            ),
        )

    try:
        mapping = settings.aad_group_role_map
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AAD_GROUP_ROLE_MAP_JSON invalid: {exc}",
        ) from exc

    # Re-use the SSO callback's mapping helper so behaviour stays consistent.
    from app.services.m365.aad_groups import map_groups_to_role

    group_ids = [g["id"] for g in stored_groups if isinstance(g, dict) and g.get("id")]
    role_str = map_groups_to_role(group_ids, mapping)

    previous_role = user.role.value if hasattr(user.role, "value") else str(user.role)

    if role_str is None:
        # No group matches → deny. Same fail-closed behaviour as the SSO
        # callback so the resync endpoint cannot accidentally grant access.
        user.is_active = False
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="admin_aad_role_denied",
                user_id=_admin.id,
                details={
                    "target_email": user.email,
                    "aad_group_count": len(stored_groups),
                    "reason": "no AAD group matched current mapping",
                },
            )
        )
        await db.flush()
        return ResyncAadGroupsResponse(
            user_id=user.id,
            email=user.email,
            aad_group_ids=stored_groups,
            previous_role=previous_role,
            new_role=previous_role,  # role unchanged — just deactivated
            role_changed=False,
            is_active=False,
        )

    new_role = UserRole(role_str)
    role_changed = user.role != new_role
    if role_changed:
        db.add(
            Activity(
                entity_type="user",
                entity_id=user.id,
                action="admin_aad_role_resynced",
                user_id=_admin.id,
                details={
                    "target_email": user.email,
                    "from": previous_role,
                    "to": new_role.value,
                },
            )
        )
        user.role = new_role
    user.is_active = True
    await db.flush()

    return ResyncAadGroupsResponse(
        user_id=user.id,
        email=user.email,
        aad_group_ids=stored_groups,
        previous_role=previous_role,
        new_role=new_role.value,
        role_changed=role_changed,
        is_active=user.is_active,
    )
