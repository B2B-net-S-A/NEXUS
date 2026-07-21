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

    routes = [
        r for r in app.routes if getattr(r, "path", "") == "/api/admin/candidate-pii-orphans"
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


async def test_all_checks_run_and_return_zero_on_fresh_db(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """A fresh migrated DB has no data, so every count is 0 and no check errors.

    This also proves each SQL statement is valid against the real schema — a
    typo'd column would surface here as an errored check, not in production.
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
    assert summary["checks_run"] == len(body["checks"])
    for check in body["checks"]:
        assert check.get("count") == 0, f"{check['key']} != 0 on a fresh DB: {check}"
    assert summary["pii_bearing_rows_surviving"] == 0
    assert summary["evidence_rows_a_hard_delete_would_destroy"] == 0


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
    """A read-only report must not import or call a deletion primitive.

    The real erasure fix is a separate destructive change; this file must stay
    a pure measurement, so a stray delete cannot sneak in under its name.
    """
    src = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "admin_candidate_pii_orphans.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("session.delete", ".delete(", "DELETE FROM", "UPDATE ", "db.execute(delete"):
        assert forbidden not in src, (
            f"read-only report contains a mutation primitive: {forbidden!r}"
        )
