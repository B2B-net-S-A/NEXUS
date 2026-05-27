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

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest.fixture
def env_with_metadata(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "abc1234")
    # Future-dated BUILT_AT — po PR13 _resolve_deployed_at() używa max(env, mtime),
    # więc env musi być świeższy niż __file__ mtime żeby wygrać.
    monkeypatch.setenv("BUILT_AT", "2099-12-31T12:00:00Z")


@pytest.mark.asyncio
async def test_api_health_returns_standard_shape(env_with_metadata):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
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
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert body["version"] == "abc1234"
    assert body["deployedAt"] == "2099-12-31T12:00:00Z"


@pytest.mark.asyncio
async def test_api_health_falls_back_to_filesystem_mtime_without_env(monkeypatch):
    """Bez BUILT_AT env, deployedAt fallback na file mtime ISO (audit-2026-05-07
    fix P1-D — statyczny BUILT_AT przed fix'em pokazywał 6 dni stary timestamp
    mimo że kontener był freshly deployed)."""
    import re

    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILT_AT", raising=False)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert body["version"] == "unknown"
    # Fallback: ISO 8601 z fileystem mtime, lub "unknown" gdy mtime nie odczytany
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    assert body["deployedAt"] == "unknown" or re.match(
        iso_pattern, body["deployedAt"]
    ), f"Expected 'unknown' or ISO timestamp, got {body['deployedAt']!r}"


@pytest.mark.asyncio
async def test_api_health_prefers_mtime_over_stale_built_at(monkeypatch):
    """Gdy BUILT_AT env jest STARSZY od __file__ mtime, mtime wygrywa.

    QA 2026-05-27: Coolify env vault miał static BUILT_AT=2026-05-01 mimo
    że kontener był rebuilt 2026-05-27. Stale env nie powinien dominować
    nad świeżym mtime. PR13 zmienia logic z 'prefer env' na 'max(env, mtime)'.
    """
    import re

    monkeypatch.setenv("BUILT_AT", "2020-01-01T00:00:00Z")  # bardzo stary

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    body = response.json()
    # mtime (recent) > BUILT_AT (2020) → mtime wygrywa.
    # __file__ jest świeży (modyfikowany w tym PR), więc deployedAt > 2020.
    assert body["deployedAt"] != "2020-01-01T00:00:00Z", (
        "Stale BUILT_AT env shouldn't dominate over fresh mtime"
    )
    iso_pattern = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"
    assert re.match(iso_pattern, body["deployedAt"]), (
        f"Expected ISO timestamp, got {body['deployedAt']!r}"
    )


@pytest.mark.asyncio
async def test_api_health_uses_future_built_at_when_set(monkeypatch):
    """Gdy BUILT_AT env jest NEWER niż mtime (np. CI sets explicit deploy
    time), env wygrywa."""
    future_built_at = "2099-12-31T23:59:59Z"
    monkeypatch.setenv("BUILT_AT", future_built_at)

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")

    body = response.json()
    assert body["deployedAt"] == future_built_at, (
        "Future-dated BUILT_AT env should win over mtime"
    )


@pytest.mark.asyncio
async def test_api_health_includes_database_check(env_with_metadata):
    """W CI postgres service jest dostępny → expect database == healthy.
    Lokalnie bez DB → expect database == unhealthy + HTTP 503.
    """
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
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
async def test_api_health_autenti_unconfigured_by_default(env_with_metadata, monkeypatch):
    monkeypatch.setattr("app.core.config.settings.AUTENTI_ENABLED", False)
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    body = response.json()
    assert body["checks"].get("autenti") == "unconfigured"


@pytest.mark.asyncio
async def test_api_health_autenti_misconfigured_when_enabled_without_creds(
    env_with_metadata, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.AUTENTI_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.AUTENTI_CLIENT_ID", "")
    monkeypatch.setattr("app.core.config.settings.AUTENTI_CLIENT_SECRET", "")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    body = response.json()
    assert body["checks"].get("autenti") == "misconfigured"


@pytest.mark.asyncio
async def test_api_health_autenti_healthy_when_fully_configured(
    env_with_metadata, monkeypatch
):
    monkeypatch.setattr("app.core.config.settings.AUTENTI_ENABLED", True)
    monkeypatch.setattr("app.core.config.settings.AUTENTI_CLIENT_ID", "test-id")
    monkeypatch.setattr(
        "app.core.config.settings.AUTENTI_CLIENT_SECRET", "test-secret"
    )
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    body = response.json()
    assert body["checks"].get("autenti") == "healthy"


@pytest.mark.asyncio
async def test_legacy_health_endpoint_still_works():
    """Backwards compat: /health zachowany jako alias przez 7 dni."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
