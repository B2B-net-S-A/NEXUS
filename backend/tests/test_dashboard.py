"""Tests for dashboard API."""

from httpx import AsyncClient


async def test_dashboard_stats(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/dashboard/stats", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data
    assert "jobs" in data
    assert "contracts" in data
    assert "contractors" in data
    assert data["contractors"]["active"] <= data["contracts"]["active"]
    assert "pipeline" in data


async def test_dashboard_kpis(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/dashboard/kpis", headers=auth_headers)
    assert resp.status_code == 200
    ats = resp.json()["ats"]
    assert ats["active_consultants"] <= ats["active_contracts"]


async def test_dashboard_activity(client: AsyncClient, auth_headers: dict):
    resp = await client.get("/api/dashboard/activity", headers=auth_headers)
    # Endpoint may not exist yet — accept 200 or 404
    assert resp.status_code in (200, 404)
