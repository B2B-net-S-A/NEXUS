from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.jwt import JWTError
from app.core.security import decode_token, token_version_matches
from app.core.session import ACCESS_COOKIE_NAME
from app.models.user import User, UserRole

security = HTTPBearer(auto_error=False)

# ── Admin "podgląd jako użytkownik" (impersonation) ──────────────────────────
#
# Admin może oglądać aplikację oczami dowolnego usera (rekruter, DL, TAC…),
# żeby zobaczyć jego widok: sidebar, "moje rekrutacje", KPI, dashboardy.
# Mechanika: po normalnej autoryzacji JWT (token ZAWSZE należy do admina)
# sprawdzamy nagłówek ``X-Impersonate-User-Id``. Jeśli obecny i request
# pochodzi od admina — efektywny ``current_user`` zostaje podmieniony na
# wskazanego usera. Token się NIE zmienia; podmiana żyje wyłącznie w obrębie
# requestu, więc wszystkie filtry ``current_user.id`` i ``has_role()`` widzą
# usera podglądanego.
#
# Bezpieczeństwo:
#   • tylko admin może impersonować (inaczej 403 — anomalia, audytowalna),
#   • TYLKO ODCZYT — dozwolone metody to GET/HEAD/OPTIONS (+ POST-owe
#     wyszukiwarki, które są read-only). Każda mutacja w trybie podglądu
#     zwraca 403, żeby admin nie stworzył/nie zmienił danych „jako ktoś inny".
IMPERSONATION_HEADER = "X-Impersonate-User-Id"
_IMPERSONATION_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
# Read-only POST-y (wyszukiwarki) — muszą działać w trybie podglądu, bo część
# list (np. kandydaci) ładuje się przez POST /api/search/*.
_IMPERSONATION_POST_ALLOW_PREFIXES = ("/api/search",)


async def _resolve_impersonation(
    request: Request,
    admin: User,
    raw_target_id: str,
    db: AsyncSession,
) -> User:
    """Podmień efektywnego usera na podglądanego (tylko dla admina, read-only)."""
    if not admin.has_role(UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tylko administrator może oglądać widok innego użytkownika",
        )

    method = request.method.upper()
    path = request.url.path
    is_read_only = method in _IMPERSONATION_SAFE_METHODS or (
        method == "POST" and path.startswith(_IMPERSONATION_POST_ALLOW_PREFIXES)
    )
    if not is_read_only:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Podgląd jako użytkownik jest tylko do odczytu",
        )

    try:
        target_id = int(raw_target_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nieprawidłowy nagłówek impersonacji",
        )

    if target_id == admin.id:
        return admin

    result = await db.execute(select(User).where(User.id == target_id))
    target = result.scalar_one_or_none()
    if target is None or not target.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Użytkownik do podglądu nie istnieje lub jest nieaktywny",
        )

    # Ślad dla downstream (audyt/logi) — kto kogo podgląda w tym requeście.
    request.state.impersonator_id = admin.id
    request.state.impersonated_user_id = target.id
    return target


async def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT token and return current user.

    Gdy admin wysyła nagłówek ``X-Impersonate-User-Id`` zwracamy usera
    podglądanego (read-only) zamiast właściciela tokenu — patrz sekcja
    „podgląd jako użytkownik" powyżej.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        raw_token = (
            credentials.credentials
            if credentials is not None
            else request.cookies.get(ACCESS_COOKIE_NAME)
        )
        if not raw_token:
            raise credentials_exception
        payload = decode_token(raw_token)
        user_id: str = payload.get("sub")
        if user_id is None or payload.get("type") != "access":
            raise credentials_exception
        user_id_int = int(user_id)
    except (JWTError, TypeError, ValueError):
        raise credentials_exception

    result = await db.execute(select(User).where(User.id == user_id_int))
    user = result.scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or not token_version_matches(payload, user.token_version)
    ):
        raise credentials_exception

    impersonate_raw = request.headers.get(IMPERSONATION_HEADER)
    if impersonate_raw:
        return await _resolve_impersonation(request, user, impersonate_raw, db)
    return user


def require_roles(*roles: UserRole):
    """Dependency factory for role-based access control.

    Since migration 0110 a user may hold multiple roles
    (``User.role`` = primary, ``User.roles`` = full set). Permission checks
    evaluate against the union via ``has_any_role`` so a hybrid
    delivery_lead+TAC user passes both ``DeliveryLeadPlus`` and ``TacPlus``.
    """

    async def _check_role(current_user: User = Depends(get_current_user)) -> User:
        if not current_user.has_any_role(*roles):
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

    if current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return current_user
    if not current_user.has_role(UserRole.delivery_lead):
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
