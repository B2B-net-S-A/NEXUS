"""Smoke tests for /api/competence-categories endpoints.

Assumes migration 0033_cc_entities has been applied (5 seed rows present).
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


pytestmark = pytest.mark.asyncio


async def test_list_competence_categories_returns_seed(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/competence-categories", headers=app_auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    slugs = {cc["slug"] for cc in data}
    # All 5 seeded CCs should be present (from migration 0033)
    expected = {
        "infrastructure_operations",
        "software_development",
        "data_ai",
        "security_quality",
        "management_delivery",
    }
    assert expected.issubset(slugs)

    # Each CC should have required shape
    for cc in data:
        assert "id" in cc
        assert "name_pl" in cc
        assert "keywords" in cc
        assert isinstance(cc["keywords"], list)


async def test_cc_list_sorted_by_display_order(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/competence-categories", headers=app_auth_headers
    )
    data = resp.json()
    orders = [cc["display_order"] for cc in data]
    assert orders == sorted(orders)


async def test_cc_recruiters_404_on_missing(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/competence-categories/99999/recruiters", headers=app_auth_headers
    )
    assert resp.status_code == 404


async def test_cc_recruiters_returns_empty_or_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    # get first CC id
    list_resp = await app_client.get(
        "/api/competence-categories", headers=app_auth_headers
    )
    cc_id = list_resp.json()[0]["id"]

    resp = await app_client.get(
        f"/api/competence-categories/{cc_id}/recruiters",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
