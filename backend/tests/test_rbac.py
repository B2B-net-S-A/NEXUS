"""
Tests dla skonsolidowanego systemu ról (Phase 8).

Sprawdza że dla każdej roli z UserRole:
- Endpointy dozwolone zwracają != 403
- Endpointy zastrzeżone zwracają 403

Uwaga: używa in-process client (ASGITransport). Nie wymaga uruchomionego
serwera — tylko Postgres z wykonanymi migracjami.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


ROLES = [
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
    UserRole.user,
]


# ── Fixture: seeded user per role ───────────────────────────────────────────


async def _seed_user(role: UserRole) -> tuple[str, str]:
    """Tworzy testowego usera z daną rolą, zwraca (email, password)."""
    unique = uuid.uuid4().hex[:8]
    email = f"rbac-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!RBAC"

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            u = User(
                email=email,
                password_hash=hash_password(password),
                name=f"RBAC Test {role.value}",
                role=role,
                is_active=True,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)

    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def rbac_client() -> AsyncClient:
    """In-process client bez rate-limit.

    raise_app_exceptions=False — testujemy *status code* gateu, a nie body.
    Niektóre endpointy mogą zwracać 500 z powodów niezwiązanych z RBAC;
    dla testów RBAC liczy się 403 vs not-403 — 500 jest akceptowalną
    wartością not-403.
    """
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture(params=ROLES)
async def role_headers(request, rbac_client: AsyncClient) -> tuple[UserRole, dict[str, str]]:
    """Parametryzowany fixture: (UserRole, auth_headers dla usera z tą rolą)."""
    role: UserRole = request.param
    email, password = await _seed_user(role)
    headers = await _login(rbac_client, email, password)
    return role, headers


# ── Macierz dozwolonych ról per endpoint ────────────────────────────────────
#
# Każdy wpis: (method, path, allowed_roles, expected_non_403_behavior).
# `allowed_roles` = role dla których spodziewamy się != 403.
# Pozostałe role muszą dostać 403.
#
# Uwaga: nie testujemy body — tylko status code gateu. Niedozwolony dostęp
# (403) jest pewniejszy niż 200 (które może być 404/422 itp. z innego powodu),
# więc asercja jest asymetryczna: „role not in allowed → status == 403".

# Endpointy GET — dostępne dla wszystkich zalogowanych:
GET_ENDPOINTS_ALL = [
    "/api/candidates",
    "/api/jobs",
    "/api/contracts",
    "/api/clients",
]

# Endpointy wymagające TacPlus (admin/delivery_lead/tac):
TAC_PLUS_ENDPOINTS = [
    ("POST", "/api/jobs"),
    ("POST", "/api/contracts"),
    ("GET", "/api/reports/recruitment"),
    ("GET", "/api/reports/sales"),
    ("GET", "/api/reports/board"),
]

# Endpointy wymagające RecruiterPlus (wszyscy poza `user`):
RECRUITER_PLUS_ENDPOINTS = [
    ("POST", "/api/candidates"),
    ("POST", "/api/pipeline/move"),
    ("POST", "/api/pipeline/bulk-move"),
]

# Endpointy wymagające DeliveryLeadPlus (admin + delivery_lead):
# Używamy mutatorów bo GET jest CurrentUser, a POST/DELETE wymagają DL+.
# Guard odpala się przed body/path validation, więc nieistniejące ID daje 403
# dla niedozwolonej roli i 4xx (nie 403) dla dozwolonej.
DELIVERY_LEAD_PLUS_ENDPOINTS = [
    ("POST", "/api/pipeline-templates"),
    ("POST", "/api/embed-init"),
    ("POST", "/api/candidates/99999/rate-history"),
]

# Endpointy admin-only:
ADMIN_ONLY_ENDPOINTS = [
    ("GET", "/api/admin/users"),
    ("GET", "/api/admin/system"),
]


ROLE_SETS = {
    "admin_only": {UserRole.admin},
    "delivery_lead_plus": {UserRole.admin, UserRole.delivery_lead},
    "tac_plus": {UserRole.admin, UserRole.delivery_lead, UserRole.tac},
    "recruiter_plus": {
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    },
    "all": set(ROLES),
}


# ── Tests ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_login_returns_role_in_token(rbac_client: AsyncClient):
    """JWT powinien zawierać claim `role` o wartości nowego enuma."""
    from jose import jwt

    from app.core.config import settings
    from app.core.security import ALGORITHM

    email, password = await _seed_user(UserRole.delivery_lead)
    resp = await rbac_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200
    token = resp.json()["access_token"]

    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    assert payload["role"] == "delivery_lead"
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_me_endpoint_returns_user_profile(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
):
    """Każda rola może pobrać własny profil przez /api/auth/me."""
    role, headers = role_headers
    resp = await rbac_client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, f"[{role.value}] /me failed"
    body = resp.json()
    assert body["role"] == role.value


@pytest.mark.asyncio
@pytest.mark.parametrize("path", GET_ENDPOINTS_ALL)
async def test_get_read_endpoints_open_to_all_authenticated(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    path: str,
):
    """Lista kandydatów/ofert/kontraktów/klientów — każdy zalogowany user widzi."""
    role, headers = role_headers
    resp = await rbac_client.get(path, headers=headers)
    # 200 lub 404/422 (np. brak parametru) — ale NIE 403.
    assert resp.status_code != 403, (
        f"[{role.value}] GET {path} unexpectedly forbidden (status={resp.status_code})"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ADMIN_ONLY_ENDPOINTS)
async def test_admin_only_endpoints_reject_non_admins(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    """Endpointy admin-only: 403 dla wszystkich poza admin."""
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers)
    if role in ROLE_SETS["admin_only"]:
        assert resp.status_code != 403, (
            f"[{role.value}] {method} {path} got 403 but should be allowed"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", TAC_PLUS_ENDPOINTS)
async def test_tac_plus_endpoints_reject_below_tac(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    """Endpointy TacPlus: 403 dla recruiter/sourcer/user; admin/DL/TAC przepuszczone."""
    role, headers = role_headers
    # POST-owy endpoint bez body da 422, ale guard odpala wcześniej niż walidacja body
    # dla TacPlus w FastAPI — więc 403 nadal trafi przed 422.
    resp = await rbac_client.request(method, path, headers=headers, json={})
    if role in ROLE_SETS["tac_plus"]:
        assert resp.status_code != 403, (
            f"[{role.value}] {method} {path} got 403 but should be allowed"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", RECRUITER_PLUS_ENDPOINTS)
async def test_recruiter_plus_endpoints_reject_viewer(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    """Endpointy RecruiterPlus: 403 tylko dla `user` (viewer)."""
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers, json={})
    if role in ROLE_SETS["recruiter_plus"]:
        assert resp.status_code != 403, (
            f"[{role.value}] {method} {path} got 403 but should be allowed"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", DELIVERY_LEAD_PLUS_ENDPOINTS)
async def test_delivery_lead_plus_endpoints(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    """Endpointy DeliveryLeadPlus: przepuszczeni tylko admin + delivery_lead."""
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers)
    if role in ROLE_SETS["delivery_lead_plus"]:
        assert resp.status_code != 403, (
            f"[{role.value}] {method} {path} got 403 but should be allowed"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_inactive_user_cannot_login(rbac_client: AsyncClient):
    """is_active=False blokuje nawet poprawne hasło."""
    email, password = await _seed_user(UserRole.recruiter)

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        u.is_active = False
        await db.commit()

    resp = await rbac_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    # 403 Account disabled
    assert resp.status_code == 403
