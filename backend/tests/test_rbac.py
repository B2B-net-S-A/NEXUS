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

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


ROLES = [
    UserRole.admin,
    UserRole.head_of_recruitment,
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
async def role_headers(
    request, rbac_client: AsyncClient
) -> tuple[UserRole, dict[str, str]]:
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
    ("POST", "/api/clients"),  # PR #17 — było CurrentUser, teraz TacPlus
    ("POST", "/api/b2b-generator/render"),
    ("GET", "/api/reports/sales"),
    ("GET", "/api/reports/board"),
]

RECRUITMENT_REPORT_ENDPOINTS = [("GET", "/api/reports/recruitment")]

# Endpointy wymagające RecruiterPlus (wszyscy poza `user`):
RECRUITER_PLUS_ENDPOINTS = [
    ("POST", "/api/candidates"),
    ("POST", "/api/pipeline/move"),
    ("POST", "/api/pipeline/bulk-move"),
]

# P1 explicit resource guards.
CONTACT_EDITOR_ENDPOINTS = [
    ("POST", "/api/contacts"),
    ("PUT", "/api/contacts/99999"),
    ("DELETE", "/api/contacts/99999"),
]

CLOUDTALK_ADMIN_ENDPOINTS = [
    ("GET", "/api/cloudtalk/agents"),
    ("POST", "/api/cloudtalk/agents/99999/assign"),
    ("DELETE", "/api/cloudtalk/agents/99999/assign"),
    ("POST", "/api/cloudtalk/sync-agents"),
]

CLOUDTALK_CALLER_ENDPOINTS = [
    ("POST", "/api/cloudtalk/initiate-call"),
]

SENSITIVE_READ_ENDPOINTS = [
    ("GET", "/api/candidates/export?format=csv&limit=1"),
    ("GET", "/api/contracts/export?format=csv&limit=1"),
    ("GET", "/api/invoices/export.csv"),
    ("GET", "/api/candidates/99999/cv-download"),
    ("GET", "/api/contracts/99999/documents/99999/download"),
    ("GET", "/api/contract-templates/99999/render?contract_id=99999"),
    ("GET", "/api/clients/99999/required-documents/99999/download"),
    ("GET", "/api/jobs/99999/champion-profile/briefing/audio-url"),
]

# Endpointy wymagające DeliveryLeadPlus (admin + delivery_lead):
# Używamy mutatorów bo GET jest CurrentUser, a POST/DELETE wymagają DL+.
# Guard odpala się przed body/path validation, więc nieistniejące ID daje 403
# dla niedozwolonej roli i 4xx (nie 403) dla dozwolonej.
DELIVERY_LEAD_PLUS_ENDPOINTS = [
    ("POST", "/api/pipeline-templates"),
    ("POST", "/api/embed-init"),
    ("POST", "/api/candidates/99999/rate-history"),
    ("DELETE", "/api/clients/99999"),  # PR #17 — DELETE client wymaga DL+
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
    "sensitive_reader": {
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    },
    "recruitment_report_reader": {
        UserRole.admin,
        UserRole.head_of_recruitment,
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
    from app.core.config import settings
    from app.core.jwt import jwt
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
@pytest.mark.parametrize("method,path", RECRUITMENT_REPORT_ENDPOINTS)
async def test_recruitment_report_matches_dashboard_role_matrix(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers)
    if role in ROLE_SETS["recruitment_report_reader"]:
        assert resp.status_code != 403
    else:
        assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", CONTACT_EDITOR_ENDPOINTS)
async def test_contact_writes_require_tac_plus(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers, json={})
    if role in ROLE_SETS["tac_plus"]:
        assert resp.status_code != 403
    else:
        assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", CLOUDTALK_ADMIN_ENDPOINTS)
async def test_cloudtalk_configuration_is_admin_only(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers, json={})
    if role is UserRole.admin:
        assert resp.status_code != 403
    else:
        assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", CLOUDTALK_CALLER_ENDPOINTS)
async def test_cloudtalk_calls_require_operational_role(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers, json={})
    if role in ROLE_SETS["recruiter_plus"]:
        assert resp.status_code != 403
    else:
        assert resp.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", SENSITIVE_READ_ENDPOINTS)
async def test_exports_and_downloads_reject_read_only_user(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers)
    if role in ROLE_SETS["sensitive_reader"]:
        assert resp.status_code != 403
    else:
        assert resp.status_code == 403


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


# ── /api/auth/change-password — self-service password update ────────────────


@pytest.mark.asyncio
async def test_change_password_rejects_wrong_current(rbac_client: AsyncClient):
    """Weryfikacja current_password — złe hasło → 401 bez zmiany hasha."""
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(rbac_client, email, password)

    resp = await rbac_client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": "wrong-password-xxx", "new_password": "brandnew123"},
    )
    assert resp.status_code == 401

    # Stare hasło wciąż działa — nie zostało nadpisane
    ok = await rbac_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_change_password_rejects_identical_new_password(
    rbac_client: AsyncClient,
):
    """Nowe hasło identyczne z obecnym → 400 (security: żadnej tautologii)."""
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(rbac_client, email, password)

    resp = await rbac_client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": password, "new_password": password},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_change_password_rejects_too_short(rbac_client: AsyncClient):
    """Pydantic validation: new_password min_length=8 → 422."""
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(rbac_client, email, password)

    resp = await rbac_client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": password, "new_password": "short1"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_change_password_happy_path_updates_hash(
    rbac_client: AsyncClient,
):
    """Poprawny flow: stare hasło przestaje działać, nowe działa."""
    email, old_password = await _seed_user(UserRole.recruiter)
    new_password = f"NewTestPass_{uuid.uuid4().hex[:8]}!"
    headers = await _login(rbac_client, email, old_password)

    resp = await rbac_client.post(
        "/api/auth/change-password",
        headers=headers,
        json={"current_password": old_password, "new_password": new_password},
    )
    assert resp.status_code == 204

    # Stare hasło już nie pasuje
    bad = await rbac_client.post(
        "/api/auth/login", json={"email": email, "password": old_password}
    )
    assert bad.status_code == 401

    # Nowe hasło działa
    good = await rbac_client.post(
        "/api/auth/login", json={"email": email, "password": new_password}
    )
    assert good.status_code == 200


@pytest.mark.asyncio
async def test_change_password_requires_auth(rbac_client: AsyncClient):
    """Bez JWT → 403 (HTTPBearer security)."""
    resp = await rbac_client.post(
        "/api/auth/change-password",
        json={"current_password": "whatever", "new_password": "whatever2"},
    )
    assert resp.status_code in (401, 403)
