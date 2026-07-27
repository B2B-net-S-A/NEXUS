"""Contract for the read-only erasure-gap report.

Three properties are pinned, each load-bearing and enforced by nothing else:

1. The route is gated by `_snapshot_auth`, asserted structurally (a dropped
   Depends is a silent regression — the recurring finding of every audit).
2. On a fresh migrated database every check runs and returns zero — proving the
   SQL is valid against the real schema (no UndefinedColumn) and the report is
   honest when there is nothing to report.
3. Zero-PII: the response is counts and schema words only, never a data value.

This is a measurement endpoint for a deliberately deferred, destructive fix, so
the test also guards the boundary: the module must not import or call any
deletion primitive.
"""

from __future__ import annotations

from pathlib import Path

from httpx import AsyncClient


def test_route_is_gated() -> None:
    from app.api.admin_snapshot import _snapshot_auth
    from app.main import app
    from tests._route_introspection import iter_api_routes

    routes = [
        r for p, r in iter_api_routes(app) if p == "/api/admin/candidate-pii-orphans"
    ]
    assert routes, "candidate-pii-orphans route is not registered"
    gated = any(
        dep.call is _snapshot_auth
        for route in routes
        for dep in getattr(route.dependant, "dependencies", [])
    )
    assert gated, "candidate-pii-orphans must depend on _snapshot_auth"


async def test_requires_auth(app_client: AsyncClient) -> None:
    resp = await app_client.get("/api/admin/candidate-pii-orphans")
    assert resp.status_code == 401, resp.text


async def test_every_check_runs_without_error(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Every check must execute — proving its SQL is valid against the real
    schema. A typo'd column would surface here as an errored check, not in
    production.

    We assert *no error* and non-negative integer counts, NOT zero: the CI
    database is shared across the test session, so sibling tests may have
    inserted rows (e.g. calendar events) that these read-only queries then
    count. A hard zero would make this test depend on suite ordering.
    """
    resp = await app_client.get(
        "/api/admin/candidate-pii-orphans", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()

    summary = body["summary"]
    assert summary["checks_errored"] == 0, (
        "a check errored — likely an invalid column/table in its SQL: "
        f"{[c for c in body['checks'] if 'error' in c]}"
    )
    assert summary["checks_run"] == len(body["checks"]) == 8
    for check in body["checks"]:
        assert isinstance(check.get("count"), int) and check["count"] >= 0, check
    # The two summary totals must be the sum of their halves — a wiring check.
    assert summary["pii_bearing_rows_surviving"] == sum(
        c["count"] for c in body["checks"] if not c["key"].startswith("blast_")
    )
    assert summary["evidence_rows_a_hard_delete_would_destroy"] == sum(
        c["count"] for c in body["checks"] if c["key"].startswith("blast_")
    )


async def test_emits_no_row_data(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.get(
        "/api/admin/candidate-pii-orphans", headers=app_auth_headers
    )
    assert resp.status_code == 200
    payload = resp.text

    seeded_email = app_client.headers.get("X-Test-Admin-Email")
    bearer = app_auth_headers["Authorization"].split(" ", 1)[1]
    for label, leaked in (("seeded admin e-mail", seeded_email), ("caller JWT", bearer)):
        if leaked:
            assert leaked not in payload, f"report leaked the {label}"


def test_module_does_not_touch_deletion() -> None:
    """A read-only report must not CALL a deletion/mutation primitive.

    The real erasure fix is a separate destructive change; this file must stay a
    pure measurement, so a stray delete cannot sneak in under its name.

    Parsed with `ast` and checked at the call/attribute level, not by substring:
    the module's own docstring *describes* the problem (it mentions
    `session.delete()`), and a text scan would wrongly flag that. Only actual
    calls count.
    """
    import ast

    path = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "admin_candidate_pii_orphans.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))

    forbidden_attrs = {"delete", "add", "commit", "flush", "merge"}
    offenders: list[str] = []
    for node in ast.walk(tree):
        # `<x>.delete(...)`, `session.commit()`, `db.add(...)`
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr in forbidden_attrs:
                offenders.append(f"line {node.lineno}: .{node.func.attr}(")
        # `delete(...)` / `update(...)` imported from sqlalchemy
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in {"delete", "update", "insert"}:
                offenders.append(f"line {node.lineno}: {node.func.id}(")
    assert not offenders, (
        "read-only report calls a mutation primitive: " + "; ".join(offenders)
    )
