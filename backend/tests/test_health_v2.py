"""Tests for /api/health (standard healthcheck shape).

Shape contract per ~/.claude/rules/deployment.md:
{
  "status": "healthy" | "degraded" | "unhealthy",
  "version": "<short_sha>" | "unknown",
  "deployedAt": "<iso_timestamp>" | "unknown",
  "checks": {"database": "healthy" | "unhealthy"}
}
HTTP 200 for healthy/degraded, 503 for unhealthy.
"""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def env_with_metadata(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    monkeypatch.setenv("BUILT_AT", "2026-04-29T12:00:00Z")


@pytest.mark.asyncio
async def test_api_health_returns_standard_shape(env_with_metadata):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert "status" in body
    assert body["status"] in {"healthy", "degraded", "unhealthy"}
    assert "version" in body
    assert "deployedAt" in body
    assert "checks" in body
    assert isinstance(body["checks"], dict)


@pytest.mark.asyncio
async def test_api_health_returns_metadata_from_env(env_with_metadata):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert body["version"] == "abc1234"
    assert body["deployedAt"] == "2026-04-29T12:00:00Z"


@pytest.mark.asyncio
async def test_api_health_falls_back_to_unknown_without_env(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILT_AT", raising=False)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert body["version"] == "unknown"
    assert body["deployedAt"] == "unknown"


@pytest.mark.asyncio
async def test_api_health_includes_database_check(env_with_metadata):
    """W CI postgres service jest dostępny → expect database == healthy.
    Lokalnie bez DB → expect database == unhealthy + HTTP 503.
    """
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert "database" in body["checks"]
    assert body["checks"]["database"] in {"healthy", "unhealthy"}

    if body["checks"]["database"] == "healthy":
        assert response.status_code == 200
        assert body["status"] == "healthy"
    else:
        assert response.status_code == 503
        assert body["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_legacy_health_endpoint_still_works():
    """Backwards compat: /health zachowany jako alias przez 7 dni."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
