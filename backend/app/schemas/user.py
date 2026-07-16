from datetime import datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: UserRole = UserRole.recruiter


class SelfRegisterRequest(BaseModel):
    """Public self-service registration body (POST /api/auth/register).

    Deliberately has NO ``role`` field — self-registered accounts are ALWAYS
    created as the read-only ``user`` (viewer) role server-side. An admin
    elevates the role afterwards in the panel. This closes the prior hole where
    the endpoint accepted an arbitrary ``role`` and anyone could self-provision
    an ``admin``.
    """

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    id: int
    email: str
    name: str
    role: UserRole
    # Multi-role (migracja 0110). Primary role lives in ``role``; the full
    # set — including any secondary roles granted via AAD RBAC or admin —
    # lives here. Frontend should prefer ``roles`` for permission checks.
    roles: list[UserRole] = []
    is_active: bool
    # Email-verification gate (migracja 0139). True dla wszystkich kont poza
    # świeżo self-zarejestrowanymi, które nie kliknęły jeszcze linku.
    email_verified: bool = True
    profile_completed: bool = False
    profile_completed_at: Optional[datetime] = None
    # Force-change-password gate (migracja 0078). Po admin-resecie hasła
    # ustawiamy True; frontend redirectuje do /profile dopóki nie zmieni.
    force_password_change: bool = False
    force_password_change_at: Optional[datetime] = None
    # Ostatnia aktywność (WS connection time z `ConnectionManager`). Pełni rolę
    # proxy "ostatniego logowania" w UI profilu — true `last_login` wymagałby
    # osobnej kolumny + login event hook (kandydat na osobne enhancement).
    last_seen_at: Optional[datetime] = None
    # Analytics v1 (plan 2026-07-16, R0): unia capabilities ze wszystkich ról.
    # Wypełniane w GET /api/auth/me; frontend używa WYŁĄCZNIE do routingu
    # i gate'owania zapytań — twarde guardy siedzą na backendzie.
    analytics_capabilities: list[str] = []
    # Tryb rolloutu Analytics v1 (off|shadow|live) — frontend NIE wykonuje
    # requestów do /api/analytics/v1 dopóki tryb != live (fail-closed;
    # w shadow legacy UI pozostaje nietknięte — plan §8).
    analytics_v1_mode: str = "off"
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
