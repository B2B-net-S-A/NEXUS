"""Idempotent CV schema safety net for an orphaned historical Alembic bookmark."""

import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.services.startup_locks import BOOT_LOCK_TIMEOUT, is_lock_timeout

CV_SCHEMA_LOCK = 734092990
_TABLE_MIGRATIONS = (
    ("cv_generation_jobs", "0290_cv_generation_jobs.py"),
    ("cv_generated_drafts", "0295_cv_generated_draft.py"),
    ("cv_generation_requests", "0297_cv_request_receipts.py"),
    ("cv_approval_jobs", "0300_cv_approval_jobs.py"),
    ("cv_source_cleanup", "0301_cv_source_cleanup.py"),
    ("cv_version_maps", "0302_cv_version_maps.py"),
)
_ADDED_COLUMNS = (
    ("client_cv_rule_previews", "with_rule_docx BYTEA"),
    ("client_cv_rule_previews", "without_rule_docx BYTEA"),
    ("cv_generated_documents", "docx_content BYTEA"),
    ("cv_generated_documents", "docx_sha256 VARCHAR(64)"),
    ("cv_generated_documents", "template_content BYTEA"),
    ("cv_generated_documents", "consent_content BYTEA"),
    ("cv_document_versions", "template_content BYTEA"),
    ("cv_document_versions", "consent_content BYTEA"),
    (
        "cv_document_versions",
        "generated_owner_id INTEGER REFERENCES cv_generated_documents(id) ON DELETE CASCADE",
    ),
    (
        "cv_generated_share_tokens",
        "document_version_id INTEGER REFERENCES cv_document_versions(id) ON DELETE CASCADE",
    ),
    (
        "cv_generation_requests",
        "preview_id INTEGER REFERENCES client_cv_rule_previews(id) ON DELETE SET NULL",
    ),
)


def ensure_cv_schema(connection):
    # Reuse canonical table definitions rather than maintaining duplicate DDL.
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for table, filename in _TABLE_MIGRATIONS:
        if not inspect(connection).has_table(table):
            spec = importlib.util.spec_from_file_location(table, versions / filename)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
    for table, definition in _ADDED_COLUMNS:
        connection.execute(
            text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {definition}")
        )
    connection.execute(
        text(
            "ALTER TABLE cv_document_versions ALTER COLUMN candidate_stage_cv_id DROP NOT NULL"
        )
    )
    connection.execute(
        text("""DO $$ BEGIN
        ALTER TABLE cv_document_versions ADD CONSTRAINT ck_cv_version_owner
        CHECK ((candidate_stage_cv_id IS NOT NULL) <> (generated_owner_id IS NOT NULL));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$""")
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_cv_generated_version ON cv_document_versions (generated_owner_id, version) WHERE candidate_stage_cv_id IS NULL"
        )
    )


def cv_schema_ready(connection) -> bool:
    """Everything `ensure_cv_schema` guarantees is already there (catalog reads only)."""
    inspector = inspect(connection)
    if not all(inspector.has_table(table) for table, _ in _TABLE_MIGRATIONS):
        return False
    columns: dict[str, dict[str, dict]] = {}
    for table, definition in _ADDED_COLUMNS:
        if not inspector.has_table(table):
            return False
        if table not in columns:
            columns[table] = {c["name"]: c for c in inspector.get_columns(table)}
        if definition.split()[0] not in columns[table]:
            return False
    owner = columns["cv_document_versions"].get("candidate_stage_cv_id")
    if owner is None or not owner["nullable"]:
        return False
    checks = inspector.get_check_constraints("cv_document_versions")
    indexes = inspector.get_indexes("cv_document_versions")
    return "ck_cv_version_owner" in {c["name"] for c in checks} and (
        "uq_cv_generated_version" in {i["name"] for i in indexes}
    )


async def main(engine=None):
    """Repair under a bounded lock wait; a timeout is fatal only if repair is needed.

    Startup stays fail-hard when the schema is incomplete — workers and ORM
    reads would fail on it anyway. But every start re-runs the idempotent DDL,
    and `ADD COLUMN IF NOT EXISTS` waits for ACCESS EXCLUSIVE even when the
    column exists. Unbounded, that hung the boot behind the nightly pg_dump
    while stalling every reader of the table queued behind the request; with
    the limit alone it would crash-loop instead. So a lock timeout on an
    already complete schema is logged and startup continues.
    """
    owns_engine = engine is None
    if engine is None:
        from app.core.database import engine as app_engine

        engine = app_engine
    try:
        try:
            async with engine.begin() as connection:
                await connection.execute(
                    text(f"SET LOCAL lock_timeout = '{BOOT_LOCK_TIMEOUT}'")
                )
                await connection.execute(
                    text("SELECT pg_advisory_xact_lock(:key)"),
                    {"key": CV_SCHEMA_LOCK},
                )
                await connection.run_sync(ensure_cv_schema)
        except DBAPIError as exc:
            if not is_lock_timeout(exc):
                raise
            async with engine.connect() as connection:
                ready = await connection.run_sync(cv_schema_ready)
            if not ready:
                raise
            print(
                "CV schema already complete; repair skipped after a lock timeout "
                "(the next start retries)"
            )
            return
        print("CV generation and approval schema verified")
    finally:
        if owns_engine:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
