from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

security = HTTPBearer()


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT token and return current user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_token(credentials.credentials)
        user_id: str = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == int(user_id)))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise credentials_exception
    return user


def require_roles(*roles: UserRole):
    """Dependency factory for role-based access control."""

    async def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires one of roles: {[r.value for r in roles]}",
            )
        return current_user

    return _check_role


# ── Named guards (hierarchiczne "role X or higher") ──────────────────────────
#
# Hierarchia:
#   admin          (5) — pełne uprawnienia, user management
#   delivery_lead  (4) — rate cards, konflikty, pipeline templates, raporty
#   tac            (3) — CRUD ofert/kontraktów, reject/offer, prep kit
#   recruiter      (2) — dodawanie kandydatów, ruchy w pipeline
#   sourcer        (2) — dodawanie kandydatów z ATS/ogłoszeń
#   user           (1) — read-only viewer (QC, klient)

CurrentUser = Annotated[User, Depends(get_current_user)]

AdminUser = Annotated[User, Depends(require_roles(UserRole.admin))]

DeliveryLeadPlus = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.delivery_lead)),
]

TacPlus = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.delivery_lead, UserRole.tac)),
]

RecruiterPlus = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.tac,
            UserRole.recruiter,
            UserRole.sourcer,
        )
    ),
]

# Backwards-compatibility alias for routers still importing the old name.
# `ManagerOrAdmin` was the pre-RBAC guard for (manager, admin). After
# consolidation it maps to DeliveryLeadPlus (admin + delivery_lead) — same
# semantic: „privileged operations beyond regular recruiters".
ManagerOrAdmin = DeliveryLeadPlus
