"""GET /api/admin/schema-drift — the measurement that decides whether prod
needs migrating forward, plus a guardrail against the head split coming back.

Three things are pinned here:

1. **The gate exists.** The endpoint's dependency chain must include
   ``_snapshot_auth``. The recurring finding across every module audit is
   sibling routers that reach the same data without a gate because the author
   forgot one — asserting the dependency structurally is stronger than
   asserting one 401 response, and it fails loudly if someone later drops the
   ``Depends``.

2. **The report is honest on a known-good schema.** The test database is built
   by ``create_all`` from the very ORM metadata the report compares against, so
   a correct implementation must find zero drift. If this ever goes red, either
   the comparison logic is wrong or a model genuinely disagrees with itself.

3. **``alembic head`` (singular) still resolves.** ``backup-drill.yml`` runs
   ``alembic upgrade head``; the moment a second head appears that command
   raises ``Multiple head revisions are present`` and the disaster-recovery
   drill silently stops verifying anything. This is the guardrail that turns a
   recurring outage into a red CI run.
"""

from __future__ import annotations

from httpx import AsyncClient


def test_schema_drift_route_is_gated() -> None:
    """The route must sit behind _snapshot_auth — not merely behind a login."""
    from app.api.admin_snapshot import _snapshot_auth
    from app.main import app

    routes = [r for r in app.routes if getattr(r, "path", "") == "/api/admin/schema-drift"]
    assert routes, "schema-drift route is not registered"

    gated = False
    for route in routes:
        for dep in getattr(route.dependant, "dependencies", []):
            if dep.call is _snapshot_auth:
                gated = True
    assert gated, "schema-drift must depend on _snapshot_auth (admin JWT or snapshot token)"


async def test_schema_drift_requires_auth(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/admin/schema-drift")
    assert resp.status_code == 401, resp.text


async def test_schema_drift_reports_no_drift_on_fresh_schema(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """The test DB is create_all'd from this exact metadata → zero drift."""
    resp = await app_client.get("/api/admin/schema-drift", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "error" not in body, body.get("error")
    summary = body["summary"]

    assert body["missing_tables"] == [], f"tables missing from a fresh DB: {body['missing_tables']}"
    assert summary["missing_columns"] == 0, f"columns missing: {body['missing_columns'][:5]}"
    assert summary["missing_enum_types"] == 0, body["missing_enum_types"]
    assert summary["missing_enum_values"] == 0, body["missing_enum_values"]
    assert body["schema_satisfies_orm"] is True


async def test_schema_drift_emits_no_row_data(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Zero-PII contract: the report may name schema objects, never rows."""
    resp = await app_client.get("/api/admin/schema-drift", headers=app_auth_headers)
    assert resp.status_code == 200
    payload = resp.text.lower()

    # The report reads information_schema/pg_catalog only, so no value that
    # could have come out of a data row may appear. These are the seeded
    # admin's own identifiers — the cheapest canary for an accidental join.
    for leaked in ("@example.com", "password", "access_token", "bearer "):
        assert leaked not in payload, f"schema report leaked {leaked!r}"


async def test_alembic_singular_head_resolves(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Guardrail: exactly one head, or backup-drill's `upgrade head` breaks."""
    resp = await app_client.get("/api/admin/schema-drift", headers=app_auth_headers)
    assert resp.status_code == 200
    alembic = resp.json()["alembic"]

    assert "code_error" not in alembic, alembic.get("code_error")
    assert alembic["code_head_count"] == 1, (
        "alembic has split into multiple heads again: "
        f"{alembic['code_heads']}. Add a merge revision — otherwise "
        "`alembic upgrade head` in backup-drill.yml raises and the "
        "disaster-recovery drill stops verifying the restore path."
    )
    assert alembic["singular_head_resolves"] is True
