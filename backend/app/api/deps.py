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

# Head of Recruitment + admin — zarządzanie strukturą zespołu rekrutacji
# (macierze sourcer×kategoria, TAC→DL, DL→klienci), edycja targetów KPI,
# zamykanie kwartałów Liga Mistrzów.
HeadOfRecruitmentPlus = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.head_of_recruitment)),
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

# Pending verification approval (migracja 0056) — admin + delivery_lead +
# head_of_recruitment mogą akceptować / odrzucać kandydatów na stage `verified`
# kiedy rate przekracza Job.salary_max. Recruiter który wrzucił NIE może sam
# akceptować — separation of duties.
ApproverPlus = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.head_of_recruitment,
        )
    ),
]

# Backwards-compatibility alias for routers still importing the old name.
# `ManagerOrAdmin` was the pre-RBAC guard for (manager, admin). After
# consolidation it maps to DeliveryLeadPlus (admin + delivery_lead) — same
# semantic: „privileged operations beyond regular recruiters".
ManagerOrAdmin = DeliveryLeadPlus


# ── DL Client Portal guards ──────────────────────────────────────────────────


async def require_dl_assigned_or_admin(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Dependency: admin/HoR globalnie OR DL z `DeliveryLeadClientAssignment`.

    FastAPI inferruje ``client_id`` z path parametru routera. Inne role
    (recruiter, sourcer, tac, user) — zawsze 403.

    Reads dla MyClients/dashboard używają tego samego guarda — DL widzi
    tylko swoich klientów (admin widzi wszystkich).
    """
    from sqlalchemy import select

    from app.models.team_structure import DeliveryLeadClientAssignment

    if current_user.role in (UserRole.admin, UserRole.head_of_recruitment):
        return current_user
    if current_user.role != UserRole.delivery_lead:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Delivery Leads or admin/head_of_recruitment may access this",
        )
    result = await db.execute(
        select(DeliveryLeadClientAssignment).where(
            DeliveryLeadClientAssignment.client_id == client_id,
            DeliveryLeadClientAssignment.delivery_lead_user_id == current_user.id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not assigned to this client",
        )
    return current_user


DlAssignedOrAdmin = Annotated[User, Depends(require_dl_assigned_or_admin)]
