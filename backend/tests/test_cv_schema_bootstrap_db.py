"""Hosted PostgreSQL test of the production fallback, isolated and rolled back."""

from uuid import uuid4
from sqlalchemy import inspect, text
from app.core.database import engine
from app.services.cv_schema_bootstrap import ensure_cv_schema


async def test_cv_bootstrap_repairs_old_schema_and_is_repeatable():
    schema = "cv_bootstrap_" + uuid4().hex
    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            for table in (
                "users",
                "cv_generated_documents",
                "client_cv_rule_previews",
                "cv_generated_share_tokens",
            ):
                await connection.execute(
                    text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)")
                )
            await connection.execute(
                text(
                    "CREATE TABLE cv_document_versions (id INTEGER PRIMARY KEY, candidate_stage_cv_id INTEGER NOT NULL, version INTEGER NOT NULL)"
                )
            )
            await connection.run_sync(ensure_cv_schema)
            await connection.run_sync(ensure_cv_schema)

            def verify(conn):
                inspector = inspect(conn)
                for table in (
                    "cv_generation_jobs",
                    "cv_generated_drafts",
                    "cv_generation_requests",
                ):
                    assert inspector.has_table(table)
                columns = {
                    row["name"]: row
                    for row in inspector.get_columns("cv_document_versions")
                }
                assert columns["candidate_stage_cv_id"]["nullable"]
                assert {
                    "generated_owner_id",
                    "template_content",
                    "consent_content",
                } <= columns.keys()
                assert "ck_cv_version_owner" in {
                    row["name"]
                    for row in inspector.get_check_constraints("cv_document_versions")
                }
                assert "uq_cv_generated_version" in {
                    row["name"] for row in inspector.get_indexes("cv_document_versions")
                }
                generated = {
                    row["name"]
                    for row in inspector.get_columns("cv_generated_documents")
                }
                assert {
                    "docx_content",
                    "docx_sha256",
                    "template_content",
                    "consent_content",
                } <= generated
                receipt_fks = inspector.get_foreign_keys("cv_generation_requests")
                preview = next(
                    row
                    for row in receipt_fks
                    if row["constrained_columns"] == ["preview_id"]
                )
                assert preview["referred_table"] == "client_cv_rule_previews"
                assert preview["options"]["ondelete"] == "SET NULL"

            await connection.run_sync(verify)
        finally:
            await transaction.rollback()
