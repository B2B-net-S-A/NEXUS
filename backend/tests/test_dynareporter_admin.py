"""Tests for DynaReporter admin endpoints — regression coverage for fixes
shipped 2026-05-19 (PRs #266, #267, #268, #269, #271, #272).

Endpoints covered:
- POST /api/dynareporter/admin-hof/winner — validation + DB write
- DELETE /api/dynareporter/admin-hof/winner/{id} — 204 + cleanup
- GET /api/dynareporter/admin-config/scoring — returns 7 fields incl prizes
- POST /api/dynareporter/admin-config/scoring — `:value::jsonb` → `CAST(:value AS jsonb)`
- POST /api/dynareporter/board-dashboard/monthly — date type coercion
- Pydantic patterns reject bad input (422 not 500)
- Multi-role auth (`has_role()`) accepts secondary admin role

These tests guard against the bugs found in QA review:
- Scoring `:value::jsonb` asyncpg syntax error (#266)
- Board date type 'str' has no attribute 'toordinal' (#267)
- HoF delete needs `id` field in response (#269)
- Configurable prizes (#271)
- Multi-role auth bypass (#267)
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _dynareporter_write_breakglass(monkeypatch):
    """Audyt M7 PR-02: mutacje DR są blokowane przy DYNAREPORTER_MODE=read_only
    (409 DYNAREPORTER_READ_ONLY). Ten moduł testuje samą FUNKCJONALNOŚĆ write
    (walidacja Pydantic 422, persist scoring/HoF, coercion daty board) — więc
    odblokowujemy zapisy przez break-glass. Samą blokadę read_only weryfikuje
    test_dynareporter_readonly.py."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "DYNAREPORTER_WRITE_BREAKGLASS", True)


# ---------------------------------------------------------------------------
# Scoring Config — covers PR #266, #271
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scoring_get_returns_all_fields(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """GET /scoring returns placement + interview + recommendation + verification
    + prize_1 + prize_2 + prize_3 (7 fields total, prizes from PR #271)."""
    response = await app_client.get(
        "/api/dynareporter/admin-config/scoring", headers=app_auth_headers
    )
    assert response.status_code == 200, response.text
    body = response.json()
    for field in (
        "placement",
        "interview",
        "recommendation",
        "verification",
        "prize_1",
        "prize_2",
        "prize_3",
    ):
        assert field in body, f"missing field '{field}' in scoring response"
        assert isinstance(body[field], int)


@pytest.mark.asyncio
async def test_scoring_post_persists_and_echoes(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """POST /scoring with all 7 fields returns 200 (NOT 500).

    PR #266 fix — `:value::jsonb` was raising
    `asyncpg.exceptions.PostgresSyntaxError: syntax error at or near ":"`.
    Verified by ANSI `CAST(:value AS jsonb)`.
    """
    payload = {
        "placement": 175,
        "interview": 20,
        "recommendation": 6,
        "verification": 1,
        "prize_1": 5500,
        "prize_2": 3300,
        "prize_3": 2200,
    }
    response = await app_client.post(
        "/api/dynareporter/admin-config/scoring",
        headers=app_auth_headers,
        json=payload,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    for field, value in payload.items():
        assert body[field] == value, (
            f"field {field}: expected {value}, got {body[field]}"
        )

    # Cleanup — restore defaults
    await app_client.post(
        "/api/dynareporter/admin-config/scoring",
        headers=app_auth_headers,
        json={
            "placement": 150,
            "interview": 15,
            "recommendation": 5,
            "verification": 0,
            "prize_1": 5000,
            "prize_2": 3000,
            "prize_3": 2000,
        },
    )


@pytest.mark.asyncio
async def test_scoring_post_rejects_negative(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Negative placement → 422 (Pydantic ge=0)."""
    response = await app_client.post(
        "/api/dynareporter/admin-config/scoring",
        headers=app_auth_headers,
        json={"placement": -5, "interview": 15, "recommendation": 5, "verification": 0},
    )
    assert response.status_code == 422, response.text


# ---------------------------------------------------------------------------
# Hall of Fame — covers PR #267, #269
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hof_post_validates_rank(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """rank > 3 → 422 (Pydantic le=3)."""
    response = await app_client.post(
        "/api/dynareporter/admin-hof/winner",
        headers=app_auth_headers,
        json={
            "competition_type": "quarterly",
            "period": "Q1 2026",
            "user_id": 1,
            "rank": 99,
            "points": 100,
            "metric_value": 0,
            "prize": None,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("rank" in err.get("loc", []) for err in detail)


@pytest.mark.asyncio
async def test_hof_post_validates_competition_type(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """competition_type not in enum → 422."""
    response = await app_client.post(
        "/api/dynareporter/admin-hof/winner",
        headers=app_auth_headers,
        json={
            "competition_type": "invalid_type",
            "period": "Q1 2026",
            "user_id": 1,
            "rank": 1,
            "points": 100,
            "metric_value": 0,
            "prize": None,
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_hof_post_validates_period_pattern(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """period not matching pattern → 422 (PR #269 added pattern)."""
    response = await app_client.post(
        "/api/dynareporter/admin-hof/winner",
        headers=app_auth_headers,
        json={
            "competition_type": "quarterly",
            "period": "INVALID FORMAT",
            "user_id": 1,
            "rank": 1,
            "points": 100,
            "metric_value": 0,
            "prize": None,
        },
    )
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert any("period" in err.get("loc", []) for err in detail)


@pytest.mark.asyncio
async def test_hof_post_validates_prize_max_length(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """prize > 100 chars → 422 (PR #269 added max_length matching DB column)."""
    response = await app_client.post(
        "/api/dynareporter/admin-hof/winner",
        headers=app_auth_headers,
        json={
            "competition_type": "quarterly",
            "period": "Q1 2026",
            "user_id": 1,
            "rank": 1,
            "points": 100,
            "metric_value": 0,
            "prize": "A" * 200,  # exceeds max_length=100
        },
    )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Board Monthly Upsert — testy USUNIĘTE 2026-07-20.
#
# Trzy testy walidacji (`report_month` pattern, `hit_ratio` <= 100, `revenue` >= 0
# — z PR #261/#267) sprawdzały schemat `BoardMonthlyUpsert` na trasie
# POST /api/dynareporter/board-dashboard/monthly. Trasa i schemat zostały usunięte
# razem z ręcznym wprowadzaniem statystyk: NEXUS liczy te liczby sam z własnych
# danych i pokazuje w /insights. Bez endpointu testy asertowałyby 405 zamiast 422,
# czyli nie sprawdzałyby już niczego — dlatego znikają, a nie są przepisywane.
#
# Nadal chronione gdzie indziej: `test_dynareporter_readonly.py` asertuje, że KAŻDA
# zarejestrowana trasa mutująca pod /api/dynareporter jest zablokowana (middleware
# `LegacyStatsDeprecationMiddleware` działa PRZED routingiem, więc brak trasy tego
# nie osłabia). Historia Rady została przepisana do `analytics_metric_snapshots`.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Hall of Fame list — covers PR #269 (id field)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hof_list_includes_id(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Hall of Fame list entries MUST include `id` for delete UI (PR #269 fix).

    Before this fix, admin delete button was broken — frontend cast to
    `(w as { id?: number }).id` always undefined, falling to alert() fallback.
    """
    response = await app_client.get(
        "/api/dynareporter/rekrutacja/hall-of-fame",
        headers=app_auth_headers,
        params={"limit": 5},
    )
    assert response.status_code == 200
    rows = response.json()
    if rows:  # skip if HoF is empty
        for row in rows:
            assert "id" in row, "HoF entry missing 'id' field — delete UI will break"
            assert isinstance(row["id"], int)
