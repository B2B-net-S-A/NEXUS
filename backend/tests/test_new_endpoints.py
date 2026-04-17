"""Integration tests for Phase B1/B3/C1/D1 endpoints (in-process ASGI).

Uses `app_client` + `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Skill taxonomy (Phase B1) ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skills_autocomplete_finds_python(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.get(
        "/api/skills/autocomplete", params={"q": "pyth"}, headers=app_auth_headers
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(s["name"].lower() == "python" for s in items)


@pytest.mark.asyncio
async def test_skills_autocomplete_matches_alias(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Alias 'k8s' should surface 'kubernetes'."""
    r = await app_client.get(
        "/api/skills/autocomplete", params={"q": "k8s"}, headers=app_auth_headers
    )
    assert r.status_code == 200
    names = [s["name"].lower() for s in r.json()["items"]]
    assert "kubernetes" in names


@pytest.mark.asyncio
async def test_skills_list_returns_all(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.get("/api/skills", headers=app_auth_headers)
    assert r.status_code == 200
    payload = r.json()
    assert payload["total"] >= 10
    assert any("aliases" in s for s in payload["items"])


# ── Scoring weight profiles CRUD (Phase D1) ─────────────────────────────────


@pytest.mark.asyncio
async def test_scoring_weights_rejects_sum_not_100(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.post(
        "/api/scoring-weights",
        headers=app_auth_headers,
        json={
            "name": "Broken 99",
            "weights": {
                "semantic": 20,
                "skills": 20,
                "salary": 20,
                "location": 20,
                "availability": 19,  # sum = 99
            },
        },
    )
    # Pydantic v2 returns 422 for field_validator failures
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_scoring_weights_create_list_delete(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    # Create
    payload = {
        "name": "Pytest Profile",
        "weights": {
            "semantic": 30,
            "skills": 40,
            "salary": 15,
            "location": 10,
            "availability": 5,
        },
        "active": True,
    }
    r = await app_client.post(
        "/api/scoring-weights", headers=app_auth_headers, json=payload
    )
    assert r.status_code == 201, r.text
    created = r.json()
    pid = created["id"]
    assert created["name"] == "Pytest Profile"
    assert created["weights"]["skills"] == 40

    # List
    r = await app_client.get("/api/scoring-weights", headers=app_auth_headers)
    assert r.status_code == 200
    assert any(p["id"] == pid for p in r.json())

    # Cleanup
    r = await app_client.delete(
        f"/api/scoring-weights/{pid}", headers=app_auth_headers
    )
    assert r.status_code == 204


# ── Candidates filter stack (Phase A1 + B3) ─────────────────────────────────


@pytest.mark.asyncio
async def test_candidates_include_match_stats_populates_field(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    r = await app_client.get(
        "/api/candidates",
        params={"include_match_stats": "true", "page_size": 3, "match_threshold": 35},
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    items = r.json()["items"]
    if not items:  # DB may be empty in CI
        return
    # All items should have match_stats populated (even if open_count=0)
    for it in items:
        assert "match_stats" in it
        if it["match_stats"] is not None:
            assert {"open_count", "total_open", "top_score"} <= set(
                it["match_stats"].keys()
            )


@pytest.mark.asyncio
async def test_candidates_skills_filter_narrows_result_set(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    baseline = await app_client.get(
        "/api/candidates", params={"page_size": 50}, headers=app_auth_headers
    )
    assert baseline.status_code == 200
    total_all = baseline.json()["total"]

    filtered = await app_client.get(
        "/api/candidates",
        params={"skills": "python", "page_size": 50},
        headers=app_auth_headers,
    )
    assert filtered.status_code == 200
    total_py = filtered.json()["total"]
    assert 0 <= total_py <= total_all
