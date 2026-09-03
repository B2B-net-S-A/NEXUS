from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    name: str
    role: UserRole = UserRole.recruiter


class SelfRegisterRequest(BaseModel):
    """Public self-service registration body (POST /api/auth/register).

    Deliberately has NO ``role`` field — self-registered accounts remain
    least-privileged legacy viewers until the provisioning policy is explicitly
    migrated. This closes the prior hole where callers could self-provision an
    ``admin``.
    """

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    name: str = Field(..., min_length=1, max_length=255)


class UserUpdate(BaseModel):
    name: Optional[str] = None
    role: Optional[UserRole] = None
    is_active: Optional[bool] = None


DashboardPreset = Literal[
    "admin-ops",
    "delivery-lead",
    "head-of-recruitment",
    "my-work",
    "finance",
]


class DashboardClientTacPair(BaseModel):
    client_id: int
    tac_user_id: int


class DashboardDataScope(BaseModel):
    kind: Literal["organization", "recruitment_org", "delivery_clients", "self"]
    user_id: int | None = None
    allowed_client_ids: list[int] = Field(default_factory=list)
    allowed_tac_user_ids: list[int] = Field(default_factory=list)
    allowed_operator_user_ids: list[int] = Field(default_factory=list)
    allowed_client_tac_pairs: list[DashboardClientTacPair] = Field(default_factory=list)


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
    authorization_version: int = 1
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
    capabilities: list[str] = Field(default_factory=list)
    # Deprecated compatibility alias. New clients use ``capabilities``.
    analytics_capabilities: list[str] = Field(default_factory=list)
    available_dashboard_presets: list[DashboardPreset] = Field(default_factory=list)
    default_dashboard_preset: DashboardPreset | None = None
    data_scope: DashboardDataScope | None = None
    # Database-backed section ceiling used by navigation and route UX. Backend
    # guards independently resolve the same policy and remain authoritative.
    effective_section_access: dict[str, Literal["none", "read", "write"]] = Field(
        default_factory=dict
    )
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
