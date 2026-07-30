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
async def test_api_health_autenti_unconfigured_by_default(
    env_with_metadata, monkeypatch
):
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
    monkeypatch.setattr("app.core.config.settings.AUTENTI_CLIENT_SECRET", "test-secret")
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health")
    body = response.json()
    assert body["checks"].get("autenti") == "healthy"


# ── /api/health/deep — core-module (schema-vs-ORM) drift gate ───────────────
# Probes each core business table with `SELECT ... LIMIT 1` so a migration
# column that never landed on prod (the alembic multi-head + partial
# entrypoint safety-net trap — e.g. 2026-07-06's `contract_candidate_rates.
# effective_to`, PR #647) turns the deploy RED instead of shipping a module
# that 503s for real users. See memory `entrypoint-safetynet-new-columns`.
CORE_DEEP_CHECK_TABLES = {
    "contracts",
    "contract_candidate_rates",
    "contract_client_rates",
    "b2b_generated_contracts",
    "candidates",
    "clients",
    "jobs",
}


@pytest.mark.asyncio
async def test_api_health_deep_returns_shape(env_with_metadata):
    """Shape holds regardless of DB availability: status/version/checks, with
    every core table present as a check key — including the contract_*_rates
    children that slipped through the fast healthcheck on 2026-07-06."""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/health/deep")

    body = response.json()
    assert body["status"] in {"healthy", "unhealthy"}
    assert body["version"] == "abc1234"
    assert isinstance(body["checks"], dict)
    assert CORE_DEEP_CHECK_TABLES.issubset(body["checks"].keys())
    assert "b2b_signature_schema" in body["checks"]
    assert "client_portfolio_import" in body["checks"]
    assert body["client_portfolio_import"]["status"] in {
        "applied",
        "not_applied",
        "inconsistent",
        "error",
    }
    assert len(body["client_portfolio_import"]["expected_source_sha256"] or "") == 64


@pytest.mark.asyncio
async def test_api_health_deep_healthy_when_schema_matches(
    env_with_metadata, monkeypatch
):
    """DB reachable + schema matches the ORM → 200 + all core probes healthy.

    CI runs `alembic upgrade heads` on a fresh Postgres before pytest, so every
    core table has the full ORM schema — this is the assertion that would have
    gone RED on the 0154 drift. Gated on DB availability so it's a no-op locally
    without Postgres (there every probe fails → 503 + unhealthy).
    """

    async def _applied_client_portfolio(*args, **kwargs):
        manifest = kwargs["manifest"]
        return {
            "expected_source_sha256": manifest["source"]["sha256"],
            "status": "applied",
            "run_id": 1,
            "applied_at": "2026-07-30T12:00:00+00:00",
            "counts": {
                "expected_manifest_rows": len(manifest["rows"]),
                "imported_manifest_rows": len(manifest["rows"]),
                "nexus_only_rows": 0,
                "audit_rows": len(manifest["rows"]),
                "unique_clients": 33,
                "portfolio_scopes": len(manifest["rows"]),
                "framework_contracts": 28,
                "category_rows": {
                    "active": 30,
                    "relationship": 3,
                    "inactive": 1,
                },
            },
        }

    monkeypatch.setattr(
        "app.services.client_portfolio_import.get_client_portfolio_import_health",
        _applied_client_portfolio,
    )

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        health = (await ac.get("/api/health")).json()
        deep_resp = await ac.get("/api/health/deep")

    deep = deep_resp.json()

    if health["checks"].get("database") == "healthy":
        assert deep_resp.status_code == 200, deep
        assert deep["status"] == "healthy"
        assert all(v == "healthy" for v in deep["checks"].values()), deep
        assert "errors" not in deep
    else:
        assert deep_resp.status_code == 503
        assert deep["status"] == "unhealthy"


@pytest.mark.asyncio
async def test_api_health_deep_returns_503_when_probe_errors(monkeypatch):
    """When a core table probe raises (schema drift or DB error), the endpoint
    degrades to 503 + status unhealthy and records the exception class per
    failing table in `errors` — the exact signal the deploy smoke-test trips on.

    Hermetic: swaps the session factory for one whose `execute` always raises,
    so no DB and no ORM-metadata mutation is involved.
    """
    import app.core.database as db_module

    class _BoomSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, *args, **kwargs):
            raise RuntimeError("simulated schema drift")

    # The endpoint does `from app.core.database import AsyncSessionLocal` at call
    # time, so patching the module attribute is enough.
    monkeypatch.setattr(db_module, "AsyncSessionLocal", lambda: _BoomSession())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        deep_resp = await ac.get("/api/health/deep")

    deep = deep_resp.json()
    assert deep_resp.status_code == 503
    assert deep["status"] == "unhealthy"
    # Every core table is reported unhealthy, each with its exception class.
    assert set(deep["checks"].values()) == {"unhealthy"}
    assert CORE_DEEP_CHECK_TABLES.issubset(deep["errors"].keys())
    assert deep["errors"]["contract_candidate_rates"] == "RuntimeError"


@pytest.mark.asyncio
async def test_api_health_deep_fails_closed_on_b2b_signature_schema(monkeypatch):
    """A partial fail-open startup backfill must make the deploy gate red even
    when every mapped-table SELECT still succeeds."""
    import app.core.database as db_module

    class _CatalogResult:
        def scalar_one(self):
            return False

    class _PartialSchemaSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def execute(self, statement, *args, **kwargs):
            if "expected_columns" in str(statement):
                return _CatalogResult()
            return object()

    monkeypatch.setattr(db_module, "AsyncSessionLocal", lambda: _PartialSchemaSession())

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        deep_resp = await ac.get("/api/health/deep")

    deep = deep_resp.json()
    assert deep_resp.status_code == 503
    assert deep["status"] == "unhealthy"
    assert deep["checks"]["b2b_signature_schema"] == "unhealthy"
    assert deep["errors"]["b2b_signature_schema"] == "SchemaMismatch"
    assert all(deep["checks"][name] == "healthy" for name in CORE_DEEP_CHECK_TABLES)


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
