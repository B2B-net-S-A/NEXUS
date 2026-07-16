"""
Phase 7d.5 — integration tests using in-process httpx.ASGITransport fixture.

Covers key Phase 1-7 endpoints with happy + auth-fail + basic edge cases.
Runs in CI against the postgres service container after alembic migrations.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient


# ── Auth ────────────────────────────────────────────────────────────────────


async def test_health_no_auth_required(app_client: AsyncClient):
    r = await app_client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


async def test_auth_me_without_token_401(app_client: AsyncClient):
    r = await app_client.get("/api/auth/me")
    assert r.status_code in (401, 403)  # FastAPI HTTPBearer returns 403 when missing


async def test_auth_me_with_token_ok(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get("/api/auth/me", headers=app_auth_headers)
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


# ── Candidates CRUD + export ────────────────────────────────────────────────


async def test_candidates_list_requires_auth(app_client: AsyncClient):
    r = await app_client.get("/api/candidates")
    assert r.status_code in (401, 403)  # FastAPI HTTPBearer returns 403 when missing


async def test_candidates_list_ok(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get("/api/candidates", headers=app_auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body


async def test_candidates_export_csv(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get(
        "/api/candidates/export?format=csv&limit=5", headers=app_auth_headers
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers.get("content-disposition", "")
    # header row always present
    assert r.text.split("\n", 1)[0].startswith("id,name,lastname,email")


async def test_candidates_export_xlsx(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get(
        "/api/candidates/export?format=xlsx&limit=5", headers=app_auth_headers
    )
    assert r.status_code == 200
    assert "spreadsheetml" in r.headers["content-type"]
    # XLSX file starts with PK (ZIP magic)
    assert r.content[:2] == b"PK"


async def test_candidates_check_duplicates(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.post(
        "/api/candidates/check-duplicates",
        json={"email": "does-not-exist-anywhere@example.com"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Pipeline templates ──────────────────────────────────────────────────────


async def test_pipeline_templates_list(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get("/api/pipeline-templates", headers=app_auth_headers)
    assert r.status_code == 200
    templates = r.json()
    assert isinstance(templates, list)
    # Default B2B template seeded by migration 0006
    assert any(t.get("is_default") for t in templates), (
        "Default template should exist after migration 0006"
    )


async def test_pipeline_stages_endpoint(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get("/api/pipeline/stages", headers=app_auth_headers)
    assert r.status_code == 200
    stages = r.json()
    assert isinstance(stages, list)
    assert len(stages) > 0
    assert all("stage" in s for s in stages)


# ── Saved searches (Phase 4, verified in 7d) ────────────────────────────────


async def test_saved_searches_create_and_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    name = f"pytest_search_{uuid.uuid4().hex[:6]}"
    create = await app_client.post(
        "/api/saved-searches",
        json={"name": name, "entity": "candidate", "filters": {"q": "senior"}},
        headers=app_auth_headers,
    )
    assert create.status_code == 201, create.text
    row = create.json()
    assert row["name"] == name
    assert row["entity"] == "candidate"

    listing = await app_client.get(
        "/api/saved-searches?entity=candidate", headers=app_auth_headers
    )
    assert listing.status_code == 200
    ids = [r["id"] for r in listing.json()]
    assert row["id"] in ids

    # Cleanup
    await app_client.delete(
        f"/api/saved-searches/{row['id']}", headers=app_auth_headers
    )


# ── Match history ───────────────────────────────────────────────────────────


async def test_match_history_list_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    """List endpoint works when no history exists (empty DB)."""
    listing = await app_client.get(
        "/api/match-history/999/999", headers=app_auth_headers
    )
    assert listing.status_code == 200
    assert listing.json() == []


# ── Embedding diagnostics ───────────────────────────────────────────────────


async def test_embed_diagnostics(app_client: AsyncClient, app_auth_headers: dict):
    r = await app_client.get("/api/embed-diagnostics", headers=app_auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert "voyage" in body
    assert "qdrant" in body


# ── Admin (RBAC check) ──────────────────────────────────────────────────────


async def test_admin_import_tasks_requires_admin(
    app_client: AsyncClient, app_auth_headers: dict
):
    # The test user IS admin (seeded by admin_user fixture) so this succeeds
    r = await app_client.get("/api/admin/import-tasks", headers=app_auth_headers)
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── Calendar iCal import (Phase 7b.6) validation ────────────────────────────


async def test_ical_import_rejects_bad_url(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.post(
        "/api/calendar/import-ical",
        json={"url": "not-a-url", "since_days": 7},
        headers=app_auth_headers,
    )
    assert r.status_code == 422
    # PR-07 tightened this to https/webcal only (SSRF containment).
    assert "https://" in r.json()["detail"]
