"""Tests for Phase 9 B4 — contract analytics endpoints."""

from httpx import AsyncClient


async def test_margin_by_contractor_shape(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/contract-analytics/margin-by-contractor", headers=app_auth_headers
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    for row in data:
        assert {
            "candidate_id",
            "candidate_name",
            "active_contracts",
            "total_monthly_margin",
            "total_monthly_revenue",
            "margin_pct",
        } <= set(row.keys())


async def test_margin_by_client_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/margin-by-client", headers=app_auth_headers
    )
    assert resp.status_code == 200
    for row in resp.json():
        assert "client_id" in row
        assert "total_monthly_margin" in row


async def test_utilization_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/utilization", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert {
        "total_candidates",
        "candidates_active",
        "candidates_on_bench",
        "utilization_pct",
        "avg_bench_days",
    } == set(body.keys())
    assert body["total_candidates"] >= body["candidates_active"]


async def test_revenue_forecast_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/contract-analytics/revenue-forecast?horizon_months=6",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["horizon_months"] == 6
    assert len(body["months"]) == 6
    for m in body["months"]:
        assert {"month", "month_label", "revenue", "margin", "active_count"} <= set(
            m.keys()
        )
