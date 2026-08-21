"""Testy kontraktu /api/analytics/v1 (plan PR 3).

Pokrywa: gating trybu (off → 503), kopertę §4.5, RBAC/capabilities per
endpoint, wariant przetargów bez kwot (viewer-safe denylist), invalid
period → 422, quality=unavailable przy wyłączonym CloudTalk.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.analytics.cache import build_cache_key
from app.analytics.capabilities import AnalyticsCapability
from app.analytics.periods import resolve_period
from app.analytics.scope import (
    Scope,
    ScopeKind,
    ensure_recruitment_user_scope,
    ensure_team_scope,
)
from app.api.deps import get_current_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole
from app.services.access_scope import (
    DashboardScope,
    ScopeKind as DashboardScopeKind,
)


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"an-v1-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!V1"
    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            db.add(
                User(
                    email=email,
                    password_hash=hash_password(password),
                    name=f"AnV1 {role.value}",
                    role=role,
                    is_active=True,
                )
            )
            await db.commit()
    return email, password


@pytest_asyncio.fixture
async def v1_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    # raise_app_exceptions=True: nieobsłużony wyjątek ma wywalić test z pełnym
    # tracebackiem zamiast anonimowego 500 (HTTPException-y i tak obsługuje
    # FastAPI, więc asercje 403/422/503 działają bez zmian).
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest.fixture
def analytics_shadow(monkeypatch):
    """Tryb shadow — endpointy v1 serwują (default w repo to off)."""
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODE", "shadow")


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _headers(client: AsyncClient, role: UserRole) -> dict[str, str]:
    email, password = await _seed_user(role)
    return await _login(client, email, password)


async def _seed_client() -> int:
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Analytics V1 {uuid.uuid4().hex[:10]}")
        db.add(client)
        await db.commit()
        await db.refresh(client)
        return client.id


async def _seed_delivery_scope() -> tuple[str, str, int, int, int]:
    """Create one exact DL→client→TAC relationship and an unrelated TAC."""

    dl_email, dl_password = await _seed_user(UserRole.delivery_lead)
    tac_email, _ = await _seed_user(UserRole.tac)
    other_email, _ = await _seed_user(UserRole.tac)
    async with AsyncSessionLocal() as db:
        dl = await db.scalar(select(User).where(User.email == dl_email))
        tac = await db.scalar(select(User).where(User.email == tac_email))
        other = await db.scalar(select(User).where(User.email == other_email))
        assert dl is not None and tac is not None and other is not None

        client = Client(name=f"Analytics DL Scope {uuid.uuid4().hex[:10]}")
        db.add(client)
        await db.flush()
        db.add_all(
            [
                DeliveryLeadClientAssignment(
                    delivery_lead_user_id=dl.id,
                    client_id=client.id,
                    is_head=False,
                ),
                ClientTacAssignment(
                    tac_user_id=tac.id,
                    client_id=client.id,
                    is_primary=False,
                ),
            ]
        )
        await db.commit()
        return dl_email, dl_password, client.id, tac.id, other.id


# ── Gating trybu ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mode_off_returns_503(v1_client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODE", "off")
    headers = await _headers(v1_client, UserRole.admin)
    for path in ("/overview", "/me/kpis", "/finance/summary", "/meta/metrics"):
        resp = await v1_client.get(f"/api/analytics/v1{path}", headers=headers)
        assert resp.status_code == 503, f"{path}: {resp.status_code}"


# ── Koperta §4.5 ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_envelope_contract(v1_client: AsyncClient, analytics_shadow):
    headers = await _headers(v1_client, UserRole.admin)
    resp = await v1_client.get("/api/analytics/v1/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["schema_version"] == "1"
    assert body["metric_version"]
    assert body["generated_at"]
    assert body["scope"] == {"kind": "organization"}
    assert body["period"]["kind"] == "month"
    assert body["period"]["timezone"] == "Europe/Warsaw"
    assert body["quality"]["status"] in ("complete", "partial", "unavailable")
    assert isinstance(body["quality"]["warnings"], list)
    assert "data" in body
    # dane overview: pełne totals (plan §3.2 — jobs.total, clients.active)
    assert set(body["data"]["jobs"].keys()) == {"total", "open"}
    assert set(body["data"]["clients"].keys()) == {"total", "active"}


@pytest.mark.asyncio
async def test_invalid_period_422(v1_client: AsyncClient, analytics_shadow):
    headers = await _headers(v1_client, UserRole.admin)
    # custom bez granic
    r1 = await v1_client.get(
        "/api/analytics/v1/overview?period=custom", headers=headers
    )
    assert r1.status_code == 422
    # custom > 366 dni
    r2 = await v1_client.get(
        "/api/analytics/v1/overview?period=custom"
        "&date_from=2026-01-01&date_to=2027-06-01",
        headers=headers,
    )
    assert r2.status_code == 422
    # nieznany kind
    r3 = await v1_client.get(
        "/api/analytics/v1/overview?period=fortnight", headers=headers
    )
    assert r3.status_code == 422


# ── RBAC / capabilities ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_retired_viewer_without_capability_gets_403(
    v1_client: AsyncClient, analytics_shadow
):
    headers = await _headers(v1_client, UserRole.user)
    for path in (
        "/overview",
        "/me/kpis",
        "/team/kpis",
        "/team/calls",
        "/finance/summary",
        "/executive/board",
        "/commercial/tenders",
        "/clients/1/operations",
        "/clients/1/finance",
        "/meta/metrics",
    ):
        resp = await v1_client.get(f"/api/analytics/v1{path}", headers=headers)
        assert resp.status_code == 403, f"{path}: {resp.status_code}"


@pytest.mark.asyncio
async def test_me_kpis_available_to_active_operational_personas(
    v1_client: AsyncClient, analytics_shadow
):
    for role in (UserRole.recruiter, UserRole.delivery_lead):
        headers = await _headers(v1_client, role)
        resp = await v1_client.get("/api/analytics/v1/me/kpis", headers=headers)
        assert resp.status_code == 200, f"[{role.value}] {resp.text}"
        data = resp.json()["data"]
        assert set(data.keys()) >= {
            "completed_calls",
            "first_verifications",
            "candidates_added",
            "first_recommendations",
            "first_placements",
        }


@pytest.mark.asyncio
async def test_user_recruitment_scope(v1_client: AsyncClient, analytics_shadow):
    """Rekruter: self OK, cudzy user 403; HoR: cudzy OK."""
    email_r, pass_r = await _seed_user(UserRole.recruiter)
    headers_r = await _login(v1_client, email_r, pass_r)
    async with AsyncSessionLocal() as db:
        me = await db.scalar(select(User).where(User.email == email_r))

    self_resp = await v1_client.get(
        f"/api/analytics/v1/recruitment/users/{me.id}", headers=headers_r
    )
    assert self_resp.status_code == 200, self_resp.text

    other_resp = await v1_client.get(
        "/api/analytics/v1/recruitment/users/999999", headers=headers_r
    )
    assert other_resp.status_code == 403

    headers_hor = await _headers(v1_client, UserRole.head_of_recruitment)
    hor_resp = await v1_client.get(
        f"/api/analytics/v1/recruitment/users/{me.id}", headers=headers_hor
    )
    assert hor_resp.status_code == 200, hor_resp.text


@pytest.mark.asyncio
async def test_delivery_lead_team_and_user_scope_follow_exact_client_tac_relation(
    v1_client: AsyncClient, analytics_shadow
):
    (
        dl_email,
        dl_password,
        client_id,
        tac_id,
        unrelated_tac_id,
    ) = await _seed_delivery_scope()
    headers = await _login(v1_client, dl_email, dl_password)

    team = await v1_client.get("/api/analytics/v1/team/kpis", headers=headers)
    assert team.status_code == 200, team.text
    team_body = team.json()
    assert team_body["scope"] == {
        "kind": "delivery_clients",
        "user_id": team_body["scope"]["user_id"],
        "allowed_user_ids": [tac_id],
        "client_tac_pairs": [
            {"client_id": client_id, "tac_user_id": tac_id},
        ],
    }
    assert {row["user_id"] for row in team_body["data"]["rows"]} == {tac_id}

    calls = await v1_client.get("/api/analytics/v1/team/calls", headers=headers)
    assert calls.status_code == 200, calls.text
    assert calls.json()["scope"]["client_tac_pairs"] == [
        {"client_id": client_id, "tac_user_id": tac_id},
    ]
    assert {row["user_id"] for row in calls.json()["data"]["rows"]} == {tac_id}

    allowed = await v1_client.get(
        f"/api/analytics/v1/recruitment/users/{tac_id}", headers=headers
    )
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["scope"]["client_tac_pairs"] == [
        {"client_id": client_id, "tac_user_id": tac_id},
    ]

    denied = await v1_client.get(
        f"/api/analytics/v1/recruitment/users/{unrelated_tac_id}",
        headers=headers,
    )
    assert denied.status_code == 403


def test_delivery_lead_cache_key_contains_exact_relationship_pairs():
    period = resolve_period(
        "month",
        now=datetime(2026, 7, 31, 12, tzinfo=ZoneInfo("Europe/Warsaw")),
    )
    capabilities = frozenset({AnalyticsCapability.VIEW_TEAM_KPI})
    diagonal = Scope(
        kind=ScopeKind.delivery_clients,
        user_id=7,
        allowed_user_ids=frozenset({101, 202}),
        client_tac_pairs=frozenset({(10, 101), (20, 202)}),
    )
    crossed = Scope(
        kind=ScopeKind.delivery_clients,
        user_id=7,
        allowed_user_ids=frozenset({101, 202}),
        client_tac_pairs=frozenset({(10, 202), (20, 101)}),
    )

    assert diagonal.cache_token() != crossed.cache_token()
    assert build_cache_key(
        "team-kpis",
        capabilities=capabilities,
        scope=diagonal,
        period=period,
    ) != build_cache_key(
        "team-kpis",
        capabilities=capabilities,
        scope=crossed,
        period=period,
    )


@pytest.mark.asyncio
async def test_delivery_lead_scope_resolver_preserves_pairs_and_denies_arbitrary_id(
    monkeypatch: pytest.MonkeyPatch,
):
    delivery_lead = User(
        id=7,
        email="scope-dl@example.com",
        name="Scoped DL",
        role=UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value],
        is_active=True,
    )
    resolved = DashboardScope(
        kind=DashboardScopeKind.delivery_clients,
        user_id=delivery_lead.id,
        allowed_client_ids=frozenset({10, 20}),
        allowed_tac_user_ids=frozenset({101, 202}),
        allowed_operator_user_ids=frozenset({101, 202}),
        allowed_client_tac_pairs=frozenset({(10, 101), (20, 202)}),
    )
    monkeypatch.setattr(
        "app.analytics.scope.resolve_dashboard_scope",
        AsyncMock(return_value=resolved),
    )

    team_scope = await ensure_team_scope(AsyncMock(), delivery_lead)
    assert team_scope.kind is ScopeKind.delivery_clients
    assert team_scope.allowed_user_ids == frozenset({101, 202})
    assert team_scope.client_tac_pairs == frozenset({(10, 101), (20, 202)})

    user_scope = await ensure_recruitment_user_scope(AsyncMock(), delivery_lead, 101)
    assert user_scope.client_tac_pairs == frozenset({(10, 101)})

    with pytest.raises(HTTPException) as exc:
        await ensure_recruitment_user_scope(AsyncMock(), delivery_lead, 999)
    assert exc.value.status_code == 403

    monkeypatch.setattr(
        "app.analytics.scope.resolve_dashboard_scope",
        AsyncMock(
            return_value=DashboardScope(
                kind=DashboardScopeKind.delivery_clients,
                user_id=delivery_lead.id,
            )
        ),
    )
    empty_scope = await ensure_team_scope(AsyncMock(), delivery_lead)
    assert empty_scope.as_payload() == {
        "kind": "delivery_clients",
        "user_id": delivery_lead.id,
        "allowed_user_ids": [],
        "client_tac_pairs": [],
    }


@pytest.mark.asyncio
async def test_tenders_values_only_with_finance(
    v1_client: AsyncClient, analytics_shadow
):
    """TAC i DL widzą przetargi bez kwot; tylko Admin może dostać wartości."""
    headers_tac = await _headers(v1_client, UserRole.tac)
    tac_resp = await v1_client.get(
        "/api/analytics/v1/commercial/tenders", headers=headers_tac
    )
    assert tac_resp.status_code == 200, tac_resp.text
    for outcome in tac_resp.json()["data"]["outcomes"]:
        assert "salary_max_sum" not in outcome, "TAC nie może dostać kwot przetargów"

    headers_dl = await _headers(v1_client, UserRole.delivery_lead)
    dl_resp = await v1_client.get(
        "/api/analytics/v1/commercial/tenders", headers=headers_dl
    )
    assert dl_resp.status_code == 200
    for outcome in dl_resp.json()["data"]["outcomes"]:
        assert "salary_max_sum" not in outcome

    headers_admin = await _headers(v1_client, UserRole.admin)
    admin_resp = await v1_client.get(
        "/api/analytics/v1/commercial/tenders", headers=headers_admin
    )
    assert admin_resp.status_code == 200
    # recruiter w ogóle bez przetargów
    headers_rec = await _headers(v1_client, UserRole.recruiter)
    rec_resp = await v1_client.get(
        "/api/analytics/v1/commercial/tenders", headers=headers_rec
    )
    assert rec_resp.status_code == 403


@pytest.mark.asyncio
async def test_finance_summary_decimal_strings(
    v1_client: AsyncClient, analytics_shadow
):
    dl_headers = await _headers(v1_client, UserRole.delivery_lead)
    denied = await v1_client.get(
        "/api/analytics/v1/finance/summary", headers=dl_headers
    )
    assert denied.status_code == 403

    from app.main import app

    finance = User(
        id=9_000_001,
        email="analytics-finance@example.com",
        name="Analytics Finance",
        role=UserRole.finance,
        roles=[UserRole.finance.value],
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: finance
    try:
        resp = await v1_client.get("/api/analytics/v1/finance/summary")
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]
        assert data["currency"] == "PLN"
        # kwoty jako decimal-string (plan §4.5), nie float
        assert data["mrr"] is None or isinstance(data["mrr"], str)
        assert data["monthly_margin"] is None or isinstance(data["monthly_margin"], str)
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_finance_persona_has_org_wide_client_finance_without_dl_assignment(
    v1_client: AsyncClient, analytics_shadow
):
    from app.main import app

    client_id = await _seed_client()
    finance = User(
        id=9_000_002,
        email="analytics-client-finance@example.com",
        name="Analytics Client Finance",
        role=UserRole.finance,
        roles=[UserRole.finance.value],
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: finance
    try:
        finance_resp = await v1_client.get(
            f"/api/analytics/v1/clients/{client_id}/finance"
        )
        assert finance_resp.status_code == 200, finance_resp.text
        assert finance_resp.json()["scope"] == {
            "kind": "client",
            "client_id": client_id,
        }

        operations_resp = await v1_client.get(
            f"/api/analytics/v1/clients/{client_id}/operations"
        )
        # Od 19.08 finance wchodzi w client-operations torem rol
        # globalno-klienckich (ma VIEW_CLIENT_OPERATIONS; dawny bounce zdjety).
        assert operations_resp.status_code == 200, operations_resp.text
    finally:
        app.dependency_overrides.pop(get_current_user, None)


@pytest.mark.asyncio
async def test_calls_quality_unavailable_when_cloudtalk_off(
    v1_client: AsyncClient, analytics_shadow, monkeypatch
):
    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    headers = await _headers(v1_client, UserRole.recruiter)
    resp = await v1_client.get("/api/analytics/v1/calls/aggregate", headers=headers)
    assert resp.status_code == 200, resp.text
    q = resp.json()["quality"]
    assert q["status"] == "unavailable"
    assert q["warnings"], "wyłączony CloudTalk musi nieść warning, nie zero"


@pytest.mark.asyncio
async def test_meta_metrics(v1_client: AsyncClient, analytics_shadow):
    headers = await _headers(v1_client, UserRole.recruiter)
    resp = await v1_client.get("/api/analytics/v1/meta/metrics", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["timezone"] == "Europe/Warsaw"
    names = {m["name"] for m in body["metrics"]}
    assert {"current_pipeline", "first_milestone", "completed_call"} <= names
    for m in body["metrics"]:
        assert m["definition"] and m["unit"] and m["source"]


# ── Nagłówki deprecation na legacy ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_legacy_endpoints_carry_deprecation_headers(v1_client: AsyncClient):
    headers = await _headers(v1_client, UserRole.admin)
    resp = await v1_client.get("/api/dashboard/stats", headers=headers)
    assert resp.status_code == 200
    assert resp.headers.get("Deprecation") == "true"
    assert "Sunset" in resp.headers
    assert "successor-version" in resp.headers.get("Link", "")
    # nie-statystyczne API bez nagłówków
    me = await v1_client.get("/api/auth/me", headers=headers)
    assert "Deprecation" not in me.headers


@pytest.mark.asyncio
async def test_canonical_surfaces_do_not_carry_deprecation_headers(
    v1_client: AsyncClient,
):
    """Kanoniczne powierzchnie nie mogą być stemplowane jako legacy.

    `/api/dashboard/v2` to bieżący kontrakt RoleDashboard (prefiks
    `/api/dashboard` łapał go omyłkowo), a `/api/competitions` to natywny,
    żywy moduł rywalizacji bez następcy w analytics_v1. Middleware dokleja
    nagłówki także do odpowiedzi 401/403, więc test nie potrzebuje loginu.
    """
    v2 = await v1_client.get("/api/dashboard/v2/my-work")
    assert v2.status_code in (401, 403)
    assert "Deprecation" not in v2.headers
    assert "Sunset" not in v2.headers

    competitions = await v1_client.get("/api/competitions/current")
    assert competitions.status_code in (401, 403)
    assert "Deprecation" not in competitions.headers
    assert "Sunset" not in competitions.headers

    # Kontrola pozytywna: prawdziwe legacy wciąż nosi pełen komplet nagłówków.
    legacy = await v1_client.get("/api/kpis/me/today")
    assert legacy.status_code in (401, 403)
    assert legacy.headers.get("Deprecation") == "true"
    assert "Sunset" in legacy.headers
    assert "successor-version" in legacy.headers.get("Link", "")

    # Granica segmentu: wyjątek obejmuje `/api/dashboard/v2` i `/v2/...`,
    # ale NIE hipotetyczne `/api/dashboard/v2-beta` (goły startswith by je
    # zwolnił). Trasa nie istnieje — middleware stempluje też 404.
    lookalike = await v1_client.get("/api/dashboard/v2-beta")
    assert lookalike.headers.get("Deprecation") == "true"
