"""Tests for /api/admin/snapshot — ops snapshot endpoint.

Shape contract:
{
  "health": {"status", "version", "deployedAt", "checks": {"database": ...}},
  "kpis": {"candidates": {...}, "jobs": {...}, "clients": {...}, ...},
  "background_tasks": {"running": int, "expected": int, "tasks": [str, ...]},
  "alembic": {"head": str|None, "applied_at": None},
  "sentry_release": str,
  "generated_at": "<iso_timestamp>",
  "auth_mode": "token" | "jwt",
  "cached": bool
}
"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app


@pytest.fixture
def configured_token(monkeypatch):
    monkeypatch.setattr(settings, "SNAPSHOT_TOKEN", "test-snapshot-token-abcdef123456")
    return "test-snapshot-token-abcdef123456"


@pytest.mark.asyncio
async def test_snapshot_requires_auth():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/admin/snapshot")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_snapshot_rejects_bad_token(configured_token):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(
            "/api/admin/snapshot",
            headers={"X-Snapshot-Token": "wrong-token"},
        )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_snapshot_accepts_valid_token_returns_shape(configured_token):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get(
            "/api/admin/snapshot",
            headers={"X-Snapshot-Token": configured_token},
        )

    assert response.status_code == 200
    body = response.json()

    # Top-level keys
    for key in (
        "health",
        "kpis",
        "background_tasks",
        "alembic",
        "sentry_release",
        "generated_at",
        "auth_mode",
        "cached",
    ):
        assert key in body, f"Missing top-level key: {key}"

    # Health shape
    assert body["health"]["status"] in {"healthy", "unhealthy"}
    assert "version" in body["health"]
    assert "deployedAt" in body["health"]
    assert "database" in body["health"]["checks"]

    # Background tasks shape
    bg = body["background_tasks"]
    assert isinstance(bg["running"], int)
    assert isinstance(bg["expected"], int)
    assert isinstance(bg["tasks"], list)

    # Alembic shape
    assert "head" in body["alembic"]

    # Auth mode reflects token path
    assert body["auth_mode"] == "token"


@pytest.mark.asyncio
async def test_snapshot_cache_marks_second_call(configured_token):
    """Second call within 30s TTL should be served from cache."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        first = await ac.get(
            "/api/admin/snapshot",
            headers={"X-Snapshot-Token": configured_token},
        )
        second = await ac.get(
            "/api/admin/snapshot",
            headers={"X-Snapshot-Token": configured_token},
        )

    assert first.status_code == 200
    assert second.status_code == 200
    # First may be cached:False, second must be cached:True
    assert second.json()["cached"] is True
