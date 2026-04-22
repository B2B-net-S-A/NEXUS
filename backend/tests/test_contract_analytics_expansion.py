"""Smoke tests for the new contract analytics endpoints."""

from httpx import AsyncClient


async def test_role_client_mix_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/role-client-mix", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "total_active" in body
    assert "rows" in body
    assert "roles" in body
    assert "clients" in body
    for row in body["rows"]:
        for key in ("role", "client_id", "client_name", "active_count", "pct_of_total"):
            assert key in row


async def test_location_distribution_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/location-distribution", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("total", "total_with_hub", "hubs", "regions"):
        assert key in body


async def test_termination_analysis_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/termination-analysis?window_months=24",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    for key in ("window_months", "total_terminated", "by_reason", "client_retention"):
        assert key in body
    for r in body["by_reason"]:
        for key in ("reason", "count", "avg_contract_days"):
            assert key in r
    for r in body["client_retention"]:
        for key in (
            "client_id",
            "client_name",
            "total_ended",
            "kept_to_end",
            "ended_early",
            "retention_pct",
        ):
            assert key in r
