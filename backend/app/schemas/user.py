from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: UserRole = UserRole.recruiter


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: UserRole
    is_active: bool
    profile_completed: bool = False
    profile_completed_at: Optional[datetime] = None
    # Force-change-password gate (migracja 0078). Po admin-resecie hasła
    # ustawiamy True; frontend redirectuje do /profile dopóki nie zmieni.
    force_password_change: bool = False
    force_password_change_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class UserList(BaseModel):
    items: list[UserResponse]
    total: int


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str
