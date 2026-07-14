"""Contract and negative tests for NEXUS liveness/readiness endpoints."""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

import app.main as main_module
from app.main import app


FULL_SHA = "a" * 40
INSTANCE_STARTED_AT = datetime(2026, 7, 14, 10, 11, 12, tzinfo=timezone.utc)
REQUIRED_CHECKS = {"build", "database", "schema", "qdrant"}
_REAL_DATABASE_PROBE = main_module._probe_database
_REAL_SCHEMA_PROBE = main_module._probe_required_schema


@pytest.fixture(autouse=True)
def deterministic_health(monkeypatch):
    """Keep contract tests hermetic; one test exercises the fresh CI DB."""

    async def _healthy() -> None:
        return None

    monkeypatch.setenv("GIT_SHA", FULL_SHA)
    monkeypatch.setenv("BUILT_AT", "2020-01-01T00:00:00Z")
    monkeypatch.setattr(main_module, "_PROCESS_STARTED_AT", INSTANCE_STARTED_AT)
    monkeypatch.setattr(main_module, "_probe_database", _healthy)
    monkeypatch.setattr(main_module, "_probe_required_schema", _healthy)
    monkeypatch.setattr(main_module, "_probe_qdrant", _healthy)

    # Optional integrations must be deterministic and healthy/unconfigured.
    monkeypatch.setattr(main_module.settings, "M365_INTEGRATION_ENABLED", False)
    monkeypatch.setattr(main_module.settings, "CLOUDTALK_ENABLED", False)
    monkeypatch.setattr(main_module.settings, "AUTENTI_ENABLED", False)
    monkeypatch.setattr(main_module.settings, "TRAFFIT_SYNC_ENABLED", False)
    monkeypatch.setattr(main_module.settings, "ANTHROPIC_API_KEY", "configured")


async def _get(path: str):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.get(path)


@pytest.mark.asyncio
async def test_api_livez_is_process_only_full_sha_and_no_store():
    response = await _get("/api/livez")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"status": "alive", "version": FULL_SHA}


@pytest.mark.asyncio
async def test_api_livez_never_echoes_malformed_build_metadata(monkeypatch):
    monkeypatch.setenv("GIT_SHA", "token=do-not-echo")

    response = await _get("/api/livez")

    assert response.status_code == 200
    assert response.json() == {"status": "alive", "version": "unknown"}
    assert "do-not-echo" not in response.text


@pytest.mark.asyncio
async def test_api_health_returns_complete_standard_contract():
    response = await _get("/api/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["status"] == "healthy"
    assert body["version"] == FULL_SHA
    assert body["deployedAt"] == "2026-07-14T10:11:12Z"
    assert REQUIRED_CHECKS.issubset(body["checks"])
    for name in REQUIRED_CHECKS:
        assert body["checks"][name]["status"] == "healthy"
        assert body["checks"][name]["critical"] is True


@pytest.mark.asyncio
async def test_deployed_at_is_instance_start_not_mutable_env(monkeypatch):
    monkeypatch.setenv("BUILT_AT", "2099-12-31T23:59:59Z")

    first = await _get("/api/health")
    second = await _get("/api/health")

    assert first.json()["deployedAt"] == "2026-07-14T10:11:12Z"
    assert second.json()["deployedAt"] == first.json()["deployedAt"]


@pytest.mark.asyncio
async def test_missing_exact_sha_fails_readiness_closed(monkeypatch):
    monkeypatch.delenv("GIT_SHA")

    response = await _get("/api/health")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "unhealthy"
    assert body["version"] == "unknown"
    assert body["checks"]["build"] == {"status": "unhealthy", "critical": True}


@pytest.mark.asyncio
async def test_database_failure_is_503_and_skips_schema_io(monkeypatch):
    schema_called = False

    async def _database_down() -> None:
        raise RuntimeError("SELECT password FROM private_users token=secret")

    async def _schema_must_not_run() -> None:
        nonlocal schema_called
        schema_called = True

    monkeypatch.setattr(main_module, "_probe_database", _database_down)
    monkeypatch.setattr(main_module, "_probe_required_schema", _schema_must_not_run)

    response = await _get("/api/health")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "unhealthy"
    assert body["checks"]["database"]["status"] == "unhealthy"
    assert body["checks"]["schema"] == {
        "status": "unhealthy",
        "critical": True,
        "state": "unavailable",
    }
    assert schema_called is False
    assert "private_users" not in response.text
    assert "password" not in response.text.lower()
    assert "secret" not in response.text.lower()


@pytest.mark.asyncio
async def test_schema_failure_is_required_503_without_internal_details(monkeypatch):
    async def _schema_down() -> None:
        raise RuntimeError(
            "SELECT * FROM contract_candidate_rates WHERE password='secret'"
        )

    monkeypatch.setattr(main_module, "_probe_required_schema", _schema_down)

    response = await _get("/api/health")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "unhealthy"
    assert body["checks"]["schema"]["status"] == "unhealthy"
    assert body["checks"]["schema"]["critical"] is True
    assert "contract_candidate_rates" not in response.text
    assert "select" not in response.text.lower()
    assert "password" not in response.text.lower()


@pytest.mark.asyncio
async def test_qdrant_failure_is_required_503(monkeypatch):
    async def _qdrant_down() -> None:
        raise RuntimeError("not exposed")

    monkeypatch.setattr(main_module, "_probe_qdrant", _qdrant_down)

    response = await _get("/api/health")

    body = response.json()
    assert response.status_code == 503
    assert body["status"] == "unhealthy"
    assert body["checks"]["qdrant"]["status"] == "unhealthy"
    assert body["checks"]["qdrant"]["critical"] is True


def test_status_calculation_cannot_omit_or_degrade_required_component():
    checks = {
        name: main_module._health_check("healthy", critical=True)
        for name in REQUIRED_CHECKS
    }
    assert main_module._readiness_status(checks) == "healthy"

    missing = dict(checks)
    missing.pop("schema")
    assert main_module._readiness_status(missing) == "unhealthy"

    required_degraded = dict(checks)
    required_degraded["qdrant"] = main_module._health_check("degraded")
    assert main_module._readiness_status(required_degraded) == "unhealthy"


def test_only_optional_failure_can_be_degraded():
    checks = {
        name: main_module._health_check("healthy", critical=True)
        for name in REQUIRED_CHECKS
    }
    checks["optional_integration"] = main_module._health_check("degraded")

    assert main_module._readiness_status(checks) == "degraded"


@pytest.mark.asyncio
async def test_autenti_unconfigured_is_noncritical(monkeypatch):
    monkeypatch.setattr(main_module.settings, "AUTENTI_ENABLED", False)

    response = await _get("/api/health")

    assert response.json()["checks"]["autenti"] == {
        "status": "healthy",
        "state": "unconfigured",
    }


@pytest.mark.asyncio
async def test_autenti_misconfigured_degrades_but_does_not_503(monkeypatch):
    monkeypatch.setattr(main_module.settings, "AUTENTI_ENABLED", True)
    monkeypatch.setattr(main_module.settings, "AUTENTI_CLIENT_ID", "")
    monkeypatch.setattr(main_module.settings, "AUTENTI_CLIENT_SECRET", "")

    response = await _get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["autenti"] == {
        "status": "degraded",
        "state": "misconfigured",
    }


@pytest.mark.asyncio
async def test_autenti_configured_is_healthy(monkeypatch):
    monkeypatch.setattr(main_module.settings, "AUTENTI_ENABLED", True)
    monkeypatch.setattr(main_module.settings, "AUTENTI_CLIENT_ID", "test-id")
    monkeypatch.setattr(main_module.settings, "AUTENTI_CLIENT_SECRET", "test-secret")

    response = await _get("/api/health")

    assert response.json()["checks"]["autenti"] == {"status": "healthy"}


@pytest.mark.asyncio
async def test_deep_endpoint_is_sanitized_readiness_alias():
    response = await _get("/api/health/deep")

    body = response.json()
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(body) == {"status", "version", "deployedAt", "checks"}
    assert REQUIRED_CHECKS.issubset(body["checks"])
    assert not {
        "contracts",
        "contract_candidate_rates",
        "contract_client_rates",
        "candidates",
        "clients",
        "jobs",
    }.intersection(body["checks"])


@pytest.mark.asyncio
async def test_shared_release_validator_accepts_real_readiness_payload(tmp_path):
    response = await _get("/api/health")
    payload_file = tmp_path / "readiness.json"
    payload_file.write_text(json.dumps(response.json()), encoding="utf-8")
    validator = (
        Path(__file__).resolve().parents[2]
        / ".standards"
        / "tools"
        / "validate_health.py"
    )

    completed = subprocess.run(
        [
            sys.executable,
            str(validator),
            "--file",
            str(payload_file),
            "--kind",
            "readiness",
            "--expected-sha",
            FULL_SHA,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "health validation passed: readiness" in completed.stdout


def test_release_pipeline_validates_readiness_not_liveness():
    root = Path(__file__).resolve().parents[2]
    workflow = (root / ".github/workflows/_reusable-coolify-release.yml").read_text(
        encoding="utf-8"
    )
    assert workflow.count("--kind readiness") == 4
    assert "--kind livez" not in workflow


def test_docker_backend_healthcheck_is_process_liveness():
    root = Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")
    backend = compose.split("\n  backend:\n", maxsplit=1)[1].split(
        "\n  frontend:\n", maxsplit=1
    )[0]
    assert "http://localhost:8000/api/livez" in backend
    assert "http://localhost:8000/api/health" not in backend


@pytest.mark.asyncio
async def test_fresh_migrated_database_resolves_required_schema():
    """CI applies Alembic head before pytest; local runs without DB may skip."""
    try:
        await _REAL_DATABASE_PROBE()
    except Exception:
        pytest.skip("fresh PostgreSQL test database is not available")

    await _REAL_SCHEMA_PROBE()


@pytest.mark.asyncio
async def test_legacy_health_endpoint_still_works():
    response = await _get("/health")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["status"] == "ok"
