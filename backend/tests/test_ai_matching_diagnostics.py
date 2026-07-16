"""Test the AI-matching diagnostics endpoint (read-only ops view)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_diagnostics_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/admin/ai-matching/diagnostics", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # All subsystem sections present.
    for key in ("flags", "version_trace", "indexing_outbox", "telemetry", "score_cache"):
        assert key in body, f"missing section {key}"

    # Flags include the plan's kill-switches (default off in CI).
    assert body["flags"]["AI_INDEX_OUTBOX_ENABLED"] is False
    assert body["flags"]["AI_SCORING_CONTRACT_V2"] is False

    # Version trace is fully populated.
    vt = body["version_trace"]
    assert vt["ranker_version"]
    assert vt["text_schema_version"]

    # The DB-backed sections resolved (real tables exist in CI) — no error note.
    assert "error" not in body["telemetry"]
    assert body["telemetry"]["impressions"] >= 0
    assert "error" not in body["score_cache"]


@pytest.mark.asyncio
async def test_diagnostics_requires_auth(app_client: AsyncClient):
    resp = await app_client.get("/api/admin/ai-matching/diagnostics")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_audit_shape(app_client: AsyncClient, app_auth_headers: dict):
    resp = await app_client.get(
        "/api/admin/ai-matching/audit", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    for key in ("alembic", "schema", "profile_budgets", "coverage"):
        assert key in body, f"missing section {key}"

    # CI DB was built by `alembic upgrade heads` → bookmark(s) exist.
    assert body["alembic"].get("bookmarks"), body["alembic"]
    # Schema inventory resolved (real pg_tables query).
    assert body["schema"].get("table_count", 0) > 0
    assert isinstance(body["schema"].get("unknown_tables"), list)
    # Profile budget detector returns the (possibly empty) lists.
    assert "profiles" in body["profile_budgets"]
    assert "over_budget" in body["profile_budgets"]
    # DB-side coverage counts resolved (Qdrant absent in CI → guarded keys).
    assert body["coverage"].get("db_candidates", -1) >= 0


@pytest.mark.asyncio
async def test_audit_requires_auth(app_client: AsyncClient):
    resp = await app_client.get("/api/admin/ai-matching/audit")
    assert resp.status_code in (401, 403)
