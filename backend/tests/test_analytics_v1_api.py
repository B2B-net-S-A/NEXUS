"""Testy kontraktu /api/analytics/v1 (plan PR 3).

Pokrywa: gating trybu (off → 503), kopertę §4.5, RBAC/capabilities per
endpoint, wariant przetargów bez kwot (viewer-safe denylist), invalid
period → 422, quality=unavailable przy wyłączonym CloudTalk.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


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
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
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
async def test_viewer_gets_aggregates_not_finance(
    v1_client: AsyncClient, analytics_shadow
):
    headers = await _headers(v1_client, UserRole.user)
    ok = await v1_client.get("/api/analytics/v1/overview", headers=headers)
    assert ok.status_code == 200, ok.text

    for path in (
        "/team/kpis",
        "/team/calls",
        "/finance/summary",
        "/executive/board",
        "/commercial/tenders",
        "/clients/1/operations",
        "/clients/1/finance",
    ):
        resp = await v1_client.get(f"/api/analytics/v1{path}", headers=headers)
        assert resp.status_code == 403, f"{path}: {resp.status_code}"


@pytest.mark.asyncio
async def test_me_kpis_available_to_everyone(v1_client: AsyncClient, analytics_shadow):
    for role in (UserRole.user, UserRole.recruiter, UserRole.delivery_lead):
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
async def test_tenders_values_only_with_finance(
    v1_client: AsyncClient, analytics_shadow
):
    """TAC widzi przetargi BEZ kwot; DL z kwotami (viewer-safe denylist)."""
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
    headers = await _headers(v1_client, UserRole.delivery_lead)
    resp = await v1_client.get("/api/analytics/v1/finance/summary", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["currency"] == "PLN"
    # kwoty jako decimal-string (plan §4.5), nie float
    assert data["mrr"] is None or isinstance(data["mrr"], str)
    assert data["monthly_margin"] is None or isinstance(data["monthly_margin"], str)


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
    headers = await _headers(v1_client, UserRole.user)
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
