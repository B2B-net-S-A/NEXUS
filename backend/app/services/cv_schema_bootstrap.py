"""Idempotent CV schema safety net for an orphaned historical Alembic bookmark."""

import asyncio
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text


def ensure_cv_schema(connection):
    # Reuse canonical table definitions rather than maintaining duplicate DDL.
    versions = Path(__file__).resolve().parents[2] / "alembic" / "versions"
    for table, filename in (
        ("cv_generation_jobs", "0290_cv_generation_jobs.py"),
        ("cv_generated_drafts", "0295_cv_generated_draft.py"),
        ("cv_generation_requests", "0297_cv_request_receipts.py"),
    ):
        if not inspect(connection).has_table(table):
            spec = importlib.util.spec_from_file_location(table, versions / filename)
            migration = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(migration)
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
    for table, definition in (
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
    ):
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


async def main():
    from app.core.database import engine

    async with engine.begin() as connection:
        await connection.execute(text("SELECT pg_advisory_xact_lock(734092990)"))
        await connection.run_sync(ensure_cv_schema)
    await engine.dispose()
    print("CV generation and approval schema verified")


if __name__ == "__main__":
    asyncio.run(main())
