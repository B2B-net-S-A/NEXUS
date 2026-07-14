"""Tests for /api/admin/snapshot — ops snapshot endpoint.

Shape contract:
{
  "health": {"status", "version", "deployedAt", "checks": {"database": ...}},
  "kpis": {"candidates": {...}, "jobs": {...}, "clients": {...}, ...},
  "background_tasks": {"running", "disabled", "completed", "crashed", ...},
  "alembic": {"head": str|None, "applied_at": None},
  "analytics_shadow": {"mode", "quality", "observed_days", ...},
  "sentry_release": str,
  "generated_at": "<iso_timestamp>",
  "auth_mode": "token" | "jwt",
  "cached": bool
}
"""

import asyncio
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.main import app
from app.api.admin_snapshot import _background_tasks_status


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
        "analytics_shadow",
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
    assert isinstance(bg["disabled"], int)
    assert isinstance(bg["completed"], int)
    assert isinstance(bg["crashed"], int)
    assert isinstance(bg["expected"], int)
    assert isinstance(bg["tasks"], list)

    # Alembic shape
    assert "head" in body["alembic"]

    # Persisted shadow parity evidence shape
    shadow = body["analytics_shadow"]
    assert shadow["mode"] in {"off", "shadow", "live"}
    assert shadow["quality"] in {"disabled", "partial", "complete", "unavailable"}
    assert isinstance(shadow["observed_days"], int)

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


@pytest.mark.asyncio
async def test_snapshot_accepts_admin_jwt(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
):
    """JWT fallback passes Request to get_current_user and accepts admin."""
    response = await app_client.get(
        "/api/admin/snapshot",
        headers=app_auth_headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["auth_mode"] == "jwt"


@pytest.mark.asyncio
async def test_background_tasks_distinguishes_lifecycle_states(monkeypatch):
    async def completed():
        return None

    async def crashed():
        raise RuntimeError("boom")

    clean_task = asyncio.create_task(completed())
    crashed_task = asyncio.create_task(crashed())
    running_task = asyncio.create_task(asyncio.sleep(60))
    disabled_task = asyncio.create_task(completed())
    await asyncio.gather(clean_task, disabled_task)
    await asyncio.wait({crashed_task})

    monkeypatch.setattr(settings, "CLOUDTALK_ENABLED", False)
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                background_tasks={
                    "clean": clean_task,
                    "crash": crashed_task,
                    "running": running_task,
                    "cloudtalk_sync": disabled_task,
                }
            )
        )
    )
    try:
        result = _background_tasks_status(request)
    finally:
        running_task.cancel()
        await asyncio.gather(running_task, return_exceptions=True)

    assert result["running"] == 1
    assert result["disabled"] == 1
    assert result["completed"] == 1
    assert result["crashed"] == 1
    assert {row["status"] for row in result["tasks"]} == {
        "running",
        "disabled",
        "completed",
        "crashed",
    }
