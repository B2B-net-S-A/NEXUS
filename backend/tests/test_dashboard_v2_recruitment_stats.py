"""Testy composite `/api/dashboard/v2/recruitment-stats` (PR 3 sekcji
„Statystyki rekrutacji").

Pokrywa: matrycę ról (6 operacyjnych OK, finance/user 403), kopertę v2
(schema_version, per-sekcyjne data_quality, default month), spójność
kafle = totals tabeli, izolację awarii źródła (blok null + partial, kafle
nadal complete), cache org-level (jeden przelicz dla wielu widzów, scope
per widz) oraz kontrakt okresów (quarter/custom/422).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.services import dashboard_v2_sources as sources

PATH = "/api/dashboard/v2/recruitment-stats"
CACHE_PREFIX = "dashv2:recruitment-stats"

EXPECTED_SECTIONS = {
    "team_funnel",
    "quarterly_league",
    "monthly_races",
    "hall_of_fame",
    "linkedin",
    "trend",
}


async def _seed_user(role: UserRole) -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"rs-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Rs"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name=f"RS {role.value}",
                role=role,
                is_active=True,
            )
        )
        await db.commit()
    return email, password


async def _headers(client: AsyncClient, role: UserRole) -> dict[str, str]:
    email, password = await _seed_user(role)
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def rs_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    await cache_invalidate(CACHE_PREFIX)
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c
    await cache_invalidate(CACHE_PREFIX)


# ── RBAC ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_every_operational_role_can_read_finance_and_viewer_cannot(
    rs_client: AsyncClient,
):
    for role in (
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.delivery_lead,
        UserRole.talent_community_manager,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.finance,
        UserRole.sourcer,
    ):
        headers = await _headers(rs_client, role)
        resp = await rs_client.get(PATH, headers=headers)
        assert resp.status_code == 200, f"{role.value}: {resp.status_code}"

    # Finance od 19.08 jest rola operacyjna — 403 zostaje dla viewera.
    for role in (UserRole.user,):
        headers = await _headers(rs_client, role)
        resp = await rs_client.get(PATH, headers=headers)
        assert resp.status_code == 403, f"{role.value}: {resp.status_code}"


# ── Koperta + spójność kafli z tabelą ────────────────────────────────────────


@pytest.mark.asyncio
async def test_envelope_sections_and_tiles_equal_table_totals(
    rs_client: AsyncClient,
):
    headers = await _headers(rs_client, UserRole.admin)
    await cache_invalidate(CACHE_PREFIX)
    resp = await rs_client.get(PATH, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["schema_version"] == "2"
    assert body["generated_at"]
    assert set(body["data_quality"]["sections"]) >= EXPECTED_SECTIONS

    data = body["data"]
    assert data["period"]["kind"] == "month"  # default (decyzja właściciela)
    assert data["period"]["timezone"] == "Europe/Warsaw"

    kpis = data["kpis"]
    assert set(kpis) == {
        "verifications",
        "recommendations",
        "interviews",
        "acceptances",
        "placements",
    }
    for kpi in kpis.values():
        assert kpi["unit"] == "count"
        assert kpi["definition"]

    # Kafle = totals tabeli (jedno przeliczenie CTE — zero rozjazdów).
    table = data["team_table"]
    assert table is not None
    totals = table["totals"]
    for key in ("verifications", "recommendations", "interviews", "acceptances"):
        assert kpis[key]["value"] == totals[key]
    assert kpis["placements"]["value"] == totals["placements"]

    # Konwersje policzone z tych samych totals; mianownik 0 → null, nie 0.
    conversions = data["conversions"]
    assert conversions is not None
    if totals["verifications"] == 0:
        assert conversions["verified_to_recommendation_pct"] is None


# ── Izolacja awarii źródła ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_source_failure_yields_null_block_and_partial_quality(
    rs_client: AsyncClient, monkeypatch
):
    async def _boom(db):
        raise RuntimeError("monthly races source down")

    monkeypatch.setattr(sources, "load_monthly_races", _boom)
    await cache_invalidate(CACHE_PREFIX)

    headers = await _headers(rs_client, UserRole.admin)
    resp = await rs_client.get(PATH, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["data"]["monthly_races"] is None
    sections = body["data_quality"]["sections"]
    assert sections["monthly_races"]["status"] == "unavailable"
    assert body["data_quality"]["status"] == "partial"
    # Kafle żyją dalej — awaria konkursów nie dotyka lejka.
    assert sections["team_funnel"]["status"] == "complete"
    assert body["data"]["kpis"]["verifications"]["quality"] == "complete"
    assert body["data"]["team_table"] is not None

    await cache_invalidate(CACHE_PREFIX)


# ── Cache org-level ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cache_is_shared_across_viewers_but_scope_is_per_viewer(
    rs_client: AsyncClient, monkeypatch
):
    calls = {"count": 0}
    original = sources.load_recruitment_team_panel

    async def _counting(db, period):
        calls["count"] += 1
        return await original(db, period)

    monkeypatch.setattr(sources, "load_recruitment_team_panel", _counting)
    await cache_invalidate(CACHE_PREFIX)

    admin_headers = await _headers(rs_client, UserRole.admin)
    recruiter_headers = await _headers(rs_client, UserRole.recruiter)

    first = await rs_client.get(PATH, headers=admin_headers)
    second = await rs_client.get(PATH, headers=recruiter_headers)
    assert first.status_code == 200 and second.status_code == 200

    # Jeden przelicz dla całej organizacji (klucz cache bez user_id)…
    assert calls["count"] == 1
    # …ale scope w kopercie odzwierciedla BIEŻĄCEGO widza, nie autora cache.
    assert first.json()["scope"]["kind"] == "organization"
    assert second.json()["scope"]["kind"] == "self"
    # Dane pod spodem identyczne dla obu widzów.
    assert first.json()["data"] == second.json()["data"]

    await cache_invalidate(CACHE_PREFIX)


# ── Okresy ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_period_contract_quarter_custom_and_422(rs_client: AsyncClient):
    headers = await _headers(rs_client, UserRole.head_of_recruitment)

    quarter = await rs_client.get(f"{PATH}?period=quarter", headers=headers)
    assert quarter.status_code == 200, quarter.text
    assert quarter.json()["data"]["period"]["kind"] == "quarter"

    custom = await rs_client.get(
        f"{PATH}?period=custom&date_from=2026-01-01&date_to=2026-01-31",
        headers=headers,
    )
    assert custom.status_code == 200, custom.text
    assert custom.json()["data"]["period"]["kind"] == "custom"

    missing_bounds = await rs_client.get(f"{PATH}?period=custom", headers=headers)
    assert missing_bounds.status_code == 422

    unknown = await rs_client.get(f"{PATH}?period=fortnight", headers=headers)
    assert unknown.status_code == 422
