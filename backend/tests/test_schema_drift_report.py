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


# Enum labels the ORM declares that `alembic upgrade heads` does NOT create.
# Every one was verified as a genuine mismatch (not a name-vs-value artifact):
# each column uses a bare `Enum(PyEnum)` with no `values_callable` and no
# `native_enum=False`, so SQLAlchemy sends the member NAME, and no migration
# anywhere adds that label.
#
#   callstatus/initiated              — written by POST /api/cloudtalk/
#                                       initiate-call. Dormant only because the
#                                       CloudTalk kill-switch is off; it fires
#                                       the moment that flag flips.
#   contracttype/zlecenie             — the type was created with the typo
#                                       'uzlecenie'; written by POST
#                                       /api/candidates/{id}/rate-history.
#   nextsteppreference/pass_          — DB has 'pass' (correct); the ORM member
#                                       is `pass_` because `pass` is a Python
#                                       keyword. The right fix is
#                                       `values_callable` on the column, NOT
#                                       adding a second label.
#   notificationtype/similar_job_     — mirrored by entrypoint.sh (2 hits), so
#   candidates                          production has it while a migrations-only
#                                       database does not. Migrations and the
#                                       safety-net have silently diverged.
#
# This is recorded rather than asserted-to-zero because it is the measured
# truth of a database built from migrations alone, and pretending otherwise
# would make the test lie. The assertion is exact-match: any NEW drift fails,
# and fixing one of these fails too, forcing this list to be updated with it.
_KNOWN_ENUM_DRIFT = {
    ("callstatus", "initiated"),
    ("contracttype", "zlecenie"),
    ("nextsteppreference", "pass_"),
    ("notificationtype", "similar_job_candidates"),
}


async def test_schema_drift_reports_only_known_drift(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Tables and columns must be clean; enum drift must match the known set."""
    resp = await app_client.get("/api/admin/schema-drift", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert "error" not in body, body.get("error")
    summary = body["summary"]

    # These two have no known exceptions — a fresh migrated database must have
    # every table and column the ORM expects.
    assert body["missing_tables"] == [], (
        f"tables missing after `alembic upgrade heads`: {body['missing_tables']}"
    )
    assert summary["missing_columns"] == 0, f"columns missing: {body['missing_columns'][:5]}"
    assert summary["missing_enum_types"] == 0, body["missing_enum_types"]

    # Indexes and foreign keys are asserted at zero deliberately. If a
    # migrated database is missing either, the failure message below is the
    # measurement — cheaper and more exact than guessing a baseline. A missing
    # index is silent performance loss; a missing foreign key is silent
    # integrity loss. Neither is caught by anything else in the stack.
    assert summary["missing_indexes"] == 0, (
        f"indexes declared by the ORM but absent from the database: {body['missing_indexes']}"
    )
    assert summary["missing_foreign_keys"] == 0, (
        "foreign keys declared by the ORM but absent from the database: "
        f"{body['missing_foreign_keys']}"
    )

    observed = {
        (entry["enum"], label)
        for entry in body["missing_enum_values"]
        for label in entry["missing"]
    }
    assert observed == _KNOWN_ENUM_DRIFT, (
        "enum drift changed.\n"
        f"  new (ORM declares a label no migration creates): {sorted(observed - _KNOWN_ENUM_DRIFT)}\n"
        f"  fixed (update _KNOWN_ENUM_DRIFT to match):       {sorted(_KNOWN_ENUM_DRIFT - observed)}"
    )


async def test_schema_drift_emits_no_row_data(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    """Zero-PII contract: the report may name schema objects, never rows.

    The canary is the seeded admin's *actual* credentials rather than generic
    words. An earlier version searched for the substring "password" and failed
    immediately — on the perfectly legitimate column name `hashed_password`.
    Schema reports are supposed to contain words like that; what they must
    never contain is a value that could only have come from a row.
    """
    resp = await app_client.get("/api/admin/schema-drift", headers=app_auth_headers)
    assert resp.status_code == 200
    payload = resp.text

    seeded_email = app_client.headers.get("X-Test-Admin-Email")
    seeded_password = app_client.headers.get("X-Test-Admin-Password")
    bearer = app_auth_headers["Authorization"].split(" ", 1)[1]

    for label, leaked in (
        ("seeded admin e-mail", seeded_email),
        ("seeded admin password", seeded_password),
        ("caller's JWT", bearer),
    ):
        if leaked:
            assert leaked not in payload, (
                f"schema report leaked the {label} — it must read "
                "information_schema/pg_catalog only, never data rows"
            )


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
