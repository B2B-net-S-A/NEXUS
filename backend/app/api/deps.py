from enum import Enum
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import (
    AnalyticsCapability,
    capabilities_for_user,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole

security = HTTPBearer()

# A passive internal viewer is deliberately aggregate-only. Keeping this gate
# in the common auth dependency prevents a forgotten router dependency or a
# directly-entered URL from exposing PII/client/financial data.
_VIEWER_SAFE_READ_PATHS = frozenset(
    {
        "/api/auth/me",
        "/api/users/me/onboarding",
        "/api/users/me/preferences",
        "/api/dashboard/stats",
        "/api/dashboard/kpis",
        "/api/postings/stats",
        "/api/analytics/v1/overview",
        "/api/analytics/v1/pipeline/snapshot",
        "/api/analytics/v1/recruitment/funnel",
        "/api/analytics/v1/sources",
        "/api/analytics/v1/calls/aggregate",
        "/api/analytics/v1/meta/metrics",
    }
)
_VIEWER_SAFE_SELF_MUTATIONS = frozenset(
    {
        "/api/auth/change-password",
        "/api/users/me/onboarding",
        "/api/users/me/preferences",
    }
)


def _enforce_passive_viewer_scope(request: Request, user: User) -> None:
    if user.get_all_roles() != {UserRole.user}:
        return
    method = request.method.upper()
    path = request.url.path.rstrip("/") or "/"
    if method in _IMPERSONATION_SAFE_METHODS and path in _VIEWER_SAFE_READ_PATHS:
        return
    if method in {"POST", "PATCH", "PUT"} and path in _VIEWER_SAFE_SELF_MUTATIONS:
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Viewer accounts can access aggregate analytics only",
    )


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
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security)],
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

    impersonate_raw = request.headers.get(IMPERSONATION_HEADER)
    effective_user = user
    if impersonate_raw:
        effective_user = await _resolve_impersonation(
            request, user, impersonate_raw, db
        )
    _enforce_passive_viewer_scope(request, effective_user)
    return effective_user


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


def require_analytics_capabilities(
    *capabilities: AnalyticsCapability,
    require_all: bool = True,
):
    """Capability dependency backed by the canonical multi-role mapping.

    Capabilities control the maximum data class a caller may access. Endpoint
    services must still apply self/team/client row scoping where applicable.
    """

    async def _check_capabilities(
        current_user: User = Depends(get_current_user),
    ) -> User:
        granted = capabilities_for_user(current_user)
        allowed = (
            all(capability in granted for capability in capabilities)
            if require_all
            else any(capability in granted for capability in capabilities)
        )
        if not allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "message": "Missing analytics capability",
                    "required": [capability.value for capability in capabilities],
                    "mode": "all" if require_all else "any",
                },
            )
        return current_user

    return _check_capabilities


class DynaReporterSection(str, Enum):
    """Legacy section identifiers stored in ``users.allowed_sections``."""

    body_leasing = "body-leasing"
    sales = "sales"
    delivery_lead = "delivery-lead"
    placements = "placements"
    clients_mrr = "clients-mrr"
    competitions = "competitions"
    przetargi = "przetargi"
    board = "board"
    sales_mgmt = "sales-mgmt"
    mindy = "mindy"
    admin = "admin"


_DYNAREPORTER_SECTION_CAPABILITY: dict[DynaReporterSection, AnalyticsCapability] = {
    DynaReporterSection.body_leasing: AnalyticsCapability.view_recruitment_team,
    DynaReporterSection.sales: AnalyticsCapability.view_recruitment_team,
    DynaReporterSection.delivery_lead: AnalyticsCapability.view_client_operations,
    DynaReporterSection.placements: AnalyticsCapability.view_recruitment_team,
    DynaReporterSection.clients_mrr: AnalyticsCapability.view_finance,
    DynaReporterSection.competitions: AnalyticsCapability.view_recruitment_team,
    DynaReporterSection.przetargi: AnalyticsCapability.view_tenders,
    DynaReporterSection.board: AnalyticsCapability.view_finance,
    DynaReporterSection.sales_mgmt: AnalyticsCapability.view_client_operations,
    DynaReporterSection.mindy: AnalyticsCapability.view_recruitment_team,
    DynaReporterSection.admin: AnalyticsCapability.manage_analytics,
}

_READ_ONLY_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def _ensure_dynareporter_enabled(request: Request, *, enforce_write_mode: bool) -> None:
    """Apply the non-bypassable DynaReporter lifecycle switch."""
    mode = settings.DYNAREPORTER_MODE
    if mode == "off":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="DynaReporter API has been retired",
        )
    if (
        enforce_write_mode
        and request.method.upper() not in _READ_ONLY_METHODS
        and mode != "admin_write"
    ):
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="DynaReporter is read-only",
        )


def require_dynareporter_section(
    section: DynaReporterSection,
    *,
    enforce_write_mode: bool = True,
):
    """Require both role capability and the legacy per-user section grant.

    A section grant can only narrow role capabilities, never expand them.
    Admins have an intentional section-list bypass because legacy admin users
    predate ``allowed_sections`` and commonly hold an empty list.
    """
    required_capability = _DYNAREPORTER_SECTION_CAPABILITY[section]

    async def _check_dynareporter_section(
        request: Request,
        current_user: User = Depends(get_current_user),
    ) -> User:
        _ensure_dynareporter_enabled(
            request,
            enforce_write_mode=enforce_write_mode,
        )
        if required_capability not in capabilities_for_user(current_user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing analytics capability: {required_capability.value}",
            )
        if current_user.has_role(UserRole.admin):
            return current_user
        if section.value not in set(current_user.allowed_sections or []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"DynaReporter section not granted: {section.value}",
            )
        return current_user

    return _check_dynareporter_section


async def require_dynareporter_access(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """Guard the profile/landing API, which is not tied to one section."""
    _ensure_dynareporter_enabled(request, enforce_write_mode=True)
    granted = capabilities_for_user(current_user)
    has_legacy_capability = bool(
        granted - {AnalyticsCapability.view_operational_aggregates}
    )
    if not has_legacy_capability:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="DynaReporter requires an operational analytics capability",
        )
    if not current_user.has_role(UserRole.admin) and not current_user.allowed_sections:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No DynaReporter sections granted",
        )
    return current_user


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


async def require_financial_dl_assigned_or_admin(
    client_id: int,
    current_user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> User:
    """Admin globally or an assigned DL; HoR never receives write finance."""

    user = await require_dl_assigned_or_admin(client_id, current_user, db)
    if not user.has_any_role(UserRole.admin, UserRole.delivery_lead):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Financial client writes require admin or delivery_lead role",
        )
    return user


FinancialDlAssignedOrAdmin = Annotated[
    User,
    Depends(require_financial_dl_assigned_or_admin),
]
