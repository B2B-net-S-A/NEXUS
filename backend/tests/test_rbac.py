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

    raise_app_exceptions=False — testujemy status code, nie traceback.
    R0 (plan 2026-07-16): HTTP 500 NIE jest akceptowalną formą odmowy —
    każda asercja "dozwolone" wymaga statusu < 500, a odmowa musi być
    czystym 403. Test z 500 = błąd aplikacji, nie RBAC-u.
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
# UWAGA (audyt M2 PR1): /api/candidates NIE jest już all-roles — rola `user`
# (read-only viewer/klient) dostaje 403 na całym module kandydatów. Pełna
# macierz modułu: tests/test_candidate_module_access.py.
GET_ENDPOINTS_ALL = [
    "/api/jobs",
    "/api/dashboard/stats",
    "/api/dashboard/kpis",
    "/api/dashboard/pipeline-funnel",
]

# R0: odczyty operacyjne (wszyscy POZA read-only viewerem `user`):
OPERATIONAL_ENDPOINTS = [
    # Audyt M2 PR1: cały moduł kandydatów odcięty od roli `user` — pełna
    # macierz w tests/test_candidate_module_access.py.
    ("GET", "/api/candidates"),
    ("GET", "/api/clients"),
    # Celowo operacyjny (nie TacPlus): team-wide agregat dla dashboardu —
    # patrz komentarz nad reports.py::report_recruitment.
    ("GET", "/api/reports/recruitment"),
    ("GET", "/api/activities/feed"),
    ("GET", "/api/activities/leaderboard"),
    ("GET", "/api/dashboard/recent-activity"),
]

# Endpointy wymagające TacPlus (admin/delivery_lead/tac):
TAC_PLUS_ENDPOINTS = [
    ("POST", "/api/jobs"),
    ("POST", "/api/contracts"),
    ("POST", "/api/clients"),  # PR #17 — było CurrentUser, teraz TacPlus
    # R0: odczyt listy kontraktów = TacPlus (kwoty redagowane per VIEW_FINANCE,
    # M5 PR-01d). Faktury zeszły na DL+ w M5 PR-01c (patrz niżej).
    ("GET", "/api/contracts"),
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
    ("DELETE", "/api/clients/99999"),  # PR #17 — DELETE client wymaga DL+
    # R0: benchmarki stawek = finanse (odczyt DL+).
    ("GET", "/api/rate-benchmarks"),
    # R0: raporty finansowe zeszły z TacPlus na DL+ (TAC bez finansów).
    ("GET", "/api/reports/sales"),
    ("GET", "/api/reports/board"),
    ("GET", "/api/reports/tenders"),
    # M5 PR-01c: faktury to w całości dane finansowe → VIEW_FINANCE (admin/DL).
    ("GET", "/api/invoices"),
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
    # R0: operacyjni = wszyscy poza read-only viewerem `user` (z HoR).
    "operational": {
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    },
    # R0: VIEW_TEAM_KPI — cudze KPI.
    "team_kpi": {
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
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
    # 200 lub 404/422 (np. brak parametru) — ale NIE 403 i NIE 5xx.
    assert resp.status_code != 403, (
        f"[{role.value}] GET {path} unexpectedly forbidden (status={resp.status_code})"
    )
    assert resp.status_code < 500, (
        f"[{role.value}] GET {path} returned {resp.status_code} — 5xx nie jest "
        "akceptowalną odpowiedzią (R0: 500 ≠ odmowa dostępu)"
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
        assert resp.status_code < 500, (
            f"[{role.value}] {method} {path} returned {resp.status_code} — "
            "5xx nie jest akceptowalną odpowiedzią (R0)"
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
        assert resp.status_code < 500, (
            f"[{role.value}] {method} {path} returned {resp.status_code} — "
            "5xx nie jest akceptowalną odpowiedzią (R0)"
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
        assert resp.status_code < 500, (
            f"[{role.value}] {method} {path} returned {resp.status_code} — "
            "5xx nie jest akceptowalną odpowiedzią (R0)"
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
        assert resp.status_code < 500, (
            f"[{role.value}] {method} {path} returned {resp.status_code} — "
            "5xx nie jest akceptowalną odpowiedzią (R0)"
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


# ── R0 (plan 2026-07-16): odczyty operacyjne — `user` (viewer) odpada ────────


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", OPERATIONAL_ENDPOINTS)
async def test_operational_endpoints_reject_viewer(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    method: str,
    path: str,
):
    """Feed/leaderboard/klienci: 403 tylko dla `user`; HoR przepuszczony."""
    role, headers = role_headers
    resp = await rbac_client.request(method, path, headers=headers)
    if role in ROLE_SETS["operational"]:
        assert resp.status_code != 403, (
            f"[{role.value}] {method} {path} got 403 but should be allowed"
        )
        assert resp.status_code < 500, (
            f"[{role.value}] {method} {path} returned {resp.status_code} — 5xx (R0)"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] {method} {path} expected 403, got {resp.status_code}"
        )


# ── R0: /api/dashboard/kpis — viewer bez imiennego rankingu ──────────────────


@pytest.mark.asyncio
async def test_dashboard_kpis_hides_ranking_from_viewer(rbac_client: AsyncClient):
    """Rola `user` dostaje agregaty, ale top_recruiters musi być puste."""
    email, password = await _seed_user(UserRole.user)
    headers = await _login(rbac_client, email, password)
    resp = await rbac_client.get("/api/dashboard/kpis", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ats"]["top_recruiters"] == [], (
        "viewer nie może dostać imiennego rankingu rekruterów"
    )
    # R0: InfraReporter zniknął z odpowiedzi (sekret usunięty z kodu).
    assert "infrareporter" not in body


# ── R0: IDOR /api/kpis/users/{id}/today ──────────────────────────────────────


@pytest.mark.asyncio
async def test_kpi_user_today_idor_blocked(rbac_client: AsyncClient):
    """Rekruter NIE może odpytać cudzych KPI; siebie — tak; admin — tak."""
    from app.core.database import AsyncSessionLocal as _S

    email_a, pass_a = await _seed_user(UserRole.recruiter)
    email_b, _ = await _seed_user(UserRole.recruiter)
    email_admin, pass_admin = await _seed_user(UserRole.admin)

    async with _S() as db:
        user_a = await db.scalar(select(User).where(User.email == email_a))
        user_b = await db.scalar(select(User).where(User.email == email_b))

    headers_a = await _login(rbac_client, email_a, pass_a)
    headers_admin = await _login(rbac_client, email_admin, pass_admin)

    # self — OK
    self_resp = await rbac_client.get(
        f"/api/kpis/users/{user_a.id}/today", headers=headers_a
    )
    assert self_resp.status_code not in (401, 403), self_resp.text
    assert self_resp.status_code < 500

    # cudze — 403
    other_resp = await rbac_client.get(
        f"/api/kpis/users/{user_b.id}/today", headers=headers_a
    )
    assert other_resp.status_code == 403, (
        f"IDOR: recruiter odpytał cudze KPI (status={other_resp.status_code})"
    )

    # admin — OK
    admin_resp = await rbac_client.get(
        f"/api/kpis/users/{user_b.id}/today", headers=headers_admin
    )
    assert admin_resp.status_code not in (401, 403), admin_resp.text
    assert admin_resp.status_code < 500


# ── R0: activities/stats — cudzy user_id wymaga team KPI ─────────────────────


@pytest.mark.asyncio
async def test_activity_stats_foreign_user_requires_team_kpi(
    rbac_client: AsyncClient,
):
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(rbac_client, email, password)

    # własne / bez user_id — OK
    ok = await rbac_client.get("/api/activities/stats", headers=headers)
    assert ok.status_code == 200, ok.text

    # cudzy user_id — 403
    resp = await rbac_client.get(
        "/api/activities/stats?user_id=999999", headers=headers
    )
    assert resp.status_code == 403, resp.text


# ── R0: DynaReporter — capability ∩ allowed_sections (fail-closed) ───────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/dynareporter/clients-mrr/summary",
        "/api/dynareporter/przetargi/project-summary",
        "/api/dynareporter/board/months",
    ],
)
async def test_dynareporter_finance_fail_closed_without_section(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    path: str,
):
    """Finansowe sekcje Dyna: bez allowed_sections nawet DL dostaje 403.

    Seedowani userzy mają allowed_sections=[] — przechodzi WYŁĄCZNIE admin
    (bez zawężenia sekcyjnego). Sekcja nigdy nie poszerza roli, a rola bez
    sekcji nie wystarcza (capability ∩ sections).
    """
    role, headers = role_headers
    resp = await rbac_client.get(path, headers=headers)
    if role is UserRole.admin:
        assert resp.status_code != 403, (
            f"[admin] GET {path} got 403 but should be allowed"
        )
        assert resp.status_code < 500
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] GET {path} expected 403 (brak sekcji), "
            f"got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_dynareporter_section_does_not_widen_role(rbac_client: AsyncClient):
    """TAC z przyznaną sekcją clients-mrr nadal NIE widzi MRR (brak VIEW_FINANCE)."""
    email, password = await _seed_user(UserRole.tac)
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        u.allowed_sections = ["clients-mrr", "przetargi", "board"]
        await db.commit()

    headers = await _login(rbac_client, email, password)
    for path in (
        "/api/dynareporter/clients-mrr/summary",
        "/api/dynareporter/przetargi/project-summary",
        "/api/dynareporter/board/months",
    ):
        resp = await rbac_client.get(path, headers=headers)
        assert resp.status_code == 403, (
            f"[tac+sekcja] GET {path} expected 403 (sekcja nie poszerza roli), "
            f"got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_dynareporter_dl_with_section_allowed(rbac_client: AsyncClient):
    """DL z sekcją clients-mrr przechodzi (VIEW_FINANCE ∩ sekcja)."""
    email, password = await _seed_user(UserRole.delivery_lead)
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        u.allowed_sections = ["clients-mrr"]
        await db.commit()

    headers = await _login(rbac_client, email, password)
    resp = await rbac_client.get(
        "/api/dynareporter/clients-mrr/summary", headers=headers
    )
    assert resp.status_code not in (401, 403), resp.text
    assert resp.status_code < 500


# ── R0: upload XLSX wycofany — 410 Gone ──────────────────────────────────────


@pytest.mark.asyncio
async def test_dynareporter_upload_gone(rbac_client: AsyncClient):
    """POST /excel: 410 dla uprawnionych, 403 dla viewera."""
    email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(rbac_client, email, password)
    resp = await rbac_client.post("/api/dynareporter/upload/excel", headers=headers)
    assert resp.status_code == 410, resp.text

    email_v, pass_v = await _seed_user(UserRole.user)
    headers_v = await _login(rbac_client, email_v, pass_v)
    resp_v = await rbac_client.post("/api/dynareporter/upload/excel", headers=headers_v)
    assert resp_v.status_code == 403, resp_v.text


# ── R0: /api/auth/me zwraca analytics_capabilities ───────────────────────────


@pytest.mark.asyncio
async def test_me_returns_analytics_capabilities(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
):
    """Każda rola dostaje analytics_capabilities; viewer tylko agregaty."""
    role, headers = role_headers
    resp = await rbac_client.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    caps = resp.json().get("analytics_capabilities")
    assert isinstance(caps, list) and caps, (
        f"[{role.value}] analytics_capabilities missing/empty: {caps}"
    )
    if role is UserRole.user:
        assert caps == ["view_operational_aggregates"]
    if role is UserRole.admin:
        assert "view_finance" in caps and "admin_analytics" in caps
    if role is UserRole.tac:
        assert "view_finance" not in caps
    if role is UserRole.head_of_recruitment:
        assert "view_finance" not in caps


# ── R0: multi-role — secondary admin przechodzi guardy adminowe ──────────────


@pytest.mark.asyncio
async def test_secondary_admin_role_passes_admin_guards(rbac_client: AsyncClient):
    """User z primary=recruiter i secondary=admin przechodzi admin-only."""
    email, password = await _seed_user(UserRole.recruiter)
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        u.roles = ["recruiter", "admin"]
        await db.commit()

    headers = await _login(rbac_client, email, password)
    resp = await rbac_client.get("/api/admin/users", headers=headers)
    assert resp.status_code not in (401, 403), resp.text
    assert resp.status_code < 500

    # capabilities też liczone z unii ról
    me = await rbac_client.get("/api/auth/me", headers=headers)
    assert "view_finance" in me.json()["analytics_capabilities"]


# ── Audyt M7 PR-01: RBAC dla pominiętych Dyna/admin routerów ─────────────────
#
# Kontekst: poprzedni R0 (#769) zabezpieczył board/clients-mrr/przetargi przez
# capability. Audyt M7 znalazł routery pominięte, wciąż na gołym CurrentUser:
# rekrutacja (imienne KPI dla viewera — P0.2), board-dashboard i clients-overview
# (P&L / revenue dla HoR mimo braku VIEW_FINANCE — P0.1), sales-mgmt/competitions/
# mindy (direct-API bypass sekcji).


@pytest.mark.asyncio
async def test_rekrutacja_dashboard_requires_ranking_capability(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
):
    """P0.2: imienny dashboard rekrutacji → VIEW_RECRUITMENT_RANKING (bez sekcji).

    Wszyscy poza `user` (viewer) przechodzą; viewer dostaje 403 także przez
    direct API (wcześniej goły CurrentUser = każdy zalogowany).
    """
    role, headers = role_headers
    # available-weeks: prosty SELECT (pusta lista na testowej DB) — ten sam
    # router-level guard co /dashboard, ale odporny na 5xx z pustych danych.
    resp = await rbac_client.get(
        "/api/dynareporter/rekrutacja/available-weeks", headers=headers
    )
    if role in ROLE_SETS["operational"]:  # wszyscy poza `user`
        assert resp.status_code != 403, (
            f"[{role.value}] rekrutacja got 403 but should be allowed"
        )
        assert resp.status_code < 500, (
            f"[{role.value}] rekrutacja returned {resp.status_code} — 5xx (R0)"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] rekrutacja expected 403 (P0.2), got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_board_dashboard_monthly_requires_view_finance(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
):
    """P0.1: board-dashboard/monthly to pełny P&L → VIEW_FINANCE {admin, DL}.

    Head of recruitment traci dostęp (nie ma VIEW_FINANCE) — dotąd wpuszczany
    przez BOARD_ALLOWED_ROLES (split-brain względem macierzy capability).
    """
    role, headers = role_headers
    resp = await rbac_client.get(
        "/api/dynareporter/board-dashboard/monthly", headers=headers
    )
    if role in ROLE_SETS["delivery_lead_plus"]:  # {admin, delivery_lead}
        assert resp.status_code != 403, (
            f"[{role.value}] board-dashboard got 403 but should be allowed"
        )
        assert resp.status_code < 500, (
            f"[{role.value}] board-dashboard returned {resp.status_code} — 5xx (R0)"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] board-dashboard expected 403 (P0.1), "
            f"got {resp.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/api/admin/clients-overview", "/api/admin/clients-overview/by-dl"],
)
async def test_clients_overview_admin_only(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    path: str,
):
    """P0.1: globalny revenue/marża per klient i DL → AdminUser.

    HoR traci dostęp (dotąd HeadOfRecruitmentPlus — HoR widział lifetime revenue
    mimo braku VIEW_FINANCE).
    """
    role, headers = role_headers
    resp = await rbac_client.get(path, headers=headers)
    if role is UserRole.admin:
        assert resp.status_code != 403, f"[admin] {path} got 403 but should pass"
        assert resp.status_code < 500
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] {path} expected 403 (P0.1), got {resp.status_code}"
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    [
        "/api/dynareporter/sales-mgmt/projects",
        "/api/dynareporter/competitions/winners",
    ],
)
async def test_dyna_section_gated_routers_fail_closed_without_section(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
    path: str,
):
    """P0.2: sales-mgmt/competitions egzekwują sekcję backendowo (GET).

    Seeded userzy mają allowed_sections=[] → przechodzi tylko admin (bez
    zawężenia sekcyjnego). Dotąd goły CurrentUser wpuszczał każdego zalogowanego
    przez direct API, mimo że frontend wymaga hasSection.
    """
    role, headers = role_headers
    resp = await rbac_client.get(path, headers=headers)
    if role is UserRole.admin:
        assert resp.status_code != 403, (
            f"[admin] GET {path} got 403 but should be allowed"
        )
        assert resp.status_code < 500, (
            f"[admin] GET {path} returned {resp.status_code} — 5xx (R0)"
        )
    else:
        assert resp.status_code == 403, (
            f"[{role.value}] GET {path} expected 403 (fail-closed bez sekcji), "
            f"got {resp.status_code}"
        )


@pytest.mark.asyncio
async def test_mindy_commentary_requires_section_non_admin(
    rbac_client: AsyncClient,
    role_headers: tuple[UserRole, dict[str, str]],
):
    """P0.2: mindy commentary (POST, wywołuje LLM) egzekwuje sekcję `mindy`.

    Testujemy tylko role non-admin bez sekcji → 403 z router-level guardu, który
    odpala PRZED handlerem (żaden token LLM nie jest palony). Admina pomijamy
    świadomie — przeszedłby guard i trafił w realne wywołanie LLM (niedostępne/
    kosztowne w CI). Wcześniej endpoint był na gołym CurrentUser (każdy zalogowany
    mógł palić tokeny).
    """
    role, headers = role_headers
    if role is UserRole.admin:
        pytest.skip("admin przechodzi guard → realne wywołanie LLM (poza zakresem)")
    resp = await rbac_client.post(
        "/api/dynareporter/mindy/commentary", headers=headers, json={}
    )
    assert resp.status_code == 403, (
        f"[{role.value}] mindy/commentary expected 403 (fail-closed bez sekcji), "
        f"got {resp.status_code}"
    )


@pytest.mark.asyncio
async def test_viewer_with_sections_still_blocked_from_recruitment_ranking(
    rbac_client: AsyncClient,
):
    """P0.2 (obrona w głąb): nawet gdyby admin nadał viewerowi sekcje, imienny
    ranking rekrutacji/konkursów pozostaje niedostępny (brak VIEW_RECRUITMENT_
    RANKING). Sekcja nigdy nie poszerza roli."""
    email, password = await _seed_user(UserRole.user)
    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        u.allowed_sections = ["competitions", "sales-mgmt", "mindy"]
        await db.commit()
    headers = await _login(rbac_client, email, password)

    # rekrutacja: brak sekcji w modelu, ale i tak wymaga RANKING → 403
    r1 = await rbac_client.get(
        "/api/dynareporter/rekrutacja/available-weeks", headers=headers
    )
    assert r1.status_code == 403, (
        f"viewer z sekcjami nadal 403 na rekrutacji, got {r1.status_code}"
    )
    # competitions winners: sekcja competitions JEST, ale RANKING brak → 403
    r2 = await rbac_client.get(
        "/api/dynareporter/competitions/winners", headers=headers
    )
    assert r2.status_code == 403, (
        f"viewer z sekcją competitions nadal 403 na winners (imienny ranking), "
        f"got {r2.status_code}"
    )
