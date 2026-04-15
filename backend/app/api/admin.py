"""Admin-only API endpoints for user management and system stats."""
import os
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract
from app.models.job import Job
from app.models.user import RecruiterRole, User, UserRole
from app.models.user_activity import UserActivity
from app.api.deps import AdminUser
from app.schemas.user import UserResponse

router = APIRouter()

# ── Schemas ──────────────────────────────────────────────────────────────────

class AdminUserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: UserRole
    recruiter_role: Optional[RecruiterRole] = None
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
    recruiter_role: Optional[RecruiterRole] = None


class AdminUserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    recruiter_role: Optional[RecruiterRole] = None
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
            recruiter_role=u.recruiter_role,
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

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=data.role,
        recruiter_role=data.recruiter_role,
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
    """Update user details (name, role, recruiter_role, is_active)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.recruiter_role is not None:
        user.recruiter_role = data.recruiter_role
    if data.is_active is not None:
        user.is_active = data.is_active

    await db.flush()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: int,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete user by setting is_active=False."""
    if admin.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.is_active = False
    await db.flush()


@router.post("/users/{user_id}/reset-password", response_model=dict)
async def reset_password(
    user_id: int,
    data: ResetPasswordRequest,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Reset a user's password (admin only)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user.password_hash = hash_password(data.new_password)
    await db.flush()
    return {"detail": "Password reset successfully"}


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
