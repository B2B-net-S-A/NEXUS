"""Replay contract for the candidate-summary security migration.

Production may receive the scoped schema from ``entrypoint.sh`` after Alembic
fails open. The application can then legitimately create more than one cache
row for a candidate before Alembic is repaired. Revision 0206 must preserve
those rows while still marking genuinely legacy rows as unservable.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0207_candidate_summary_security.py"
    )
    spec = importlib.util.spec_from_file_location(
        "candidate_summary_security_0206_replay",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0206_quarantines_only_rows_that_still_have_a_legacy_marker():
    source = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0207_candidate_summary_security.py"
    ).read_text(encoding="utf-8")

    assert "WHERE visibility_scope_hash = 'legacy-unscoped'" in source
    assert "OR content_policy_version = 'legacy-unscoped'" in source


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="PostgreSQL migration replay; hosted CI provides DATABASE_URL",
)
@pytest.mark.asyncio
async def test_0206_replays_after_fallback_with_two_scopes_for_one_candidate():
    from app.core.database import engine

    migration = _load_migration()
    schema = f"candidate_summary_0206_{uuid.uuid4().hex}"
    scope_a = "a" * 64
    scope_b = "b" * 64
    source_a = "c" * 64
    source_b = "d" * 64
    current_policy = "candidate-summary-no-finance-v3"

    async with engine.connect() as connection:
        transaction = await connection.begin()
        try:
            await connection.execute(text(f'CREATE SCHEMA "{schema}"'))
            await connection.execute(
                text(f'SET LOCAL search_path TO "{schema}"')
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE candidates (
                        id INTEGER PRIMARY KEY
                    )
                    """
                )
            )
            await connection.execute(
                text(
                    """
                    CREATE TABLE candidate_activity_summaries (
                        id SERIAL PRIMARY KEY,
                        candidate_id INTEGER NOT NULL
                            REFERENCES candidates(id) ON DELETE CASCADE,
                        summary TEXT NULL,
                        model VARCHAR(64) NULL,
                        input_hash VARCHAR(64) NOT NULL,
                        source_version VARCHAR(64) NULL,
                        visibility_scope_hash VARCHAR(64) NOT NULL
                            DEFAULT 'legacy-unscoped',
                        content_policy_version VARCHAR(64) NOT NULL
                            DEFAULT 'legacy-unscoped',
                        source_manifest JSONB NOT NULL DEFAULT '{}'::jsonb,
                        generated_by INTEGER NULL
                            REFERENCES users(id) ON DELETE SET NULL,
                        generated_at TIMESTAMPTZ NULL,
                        generation_lease_token VARCHAR(36) NULL,
                        generation_lease_expires_at TIMESTAMPTZ NULL,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        CONSTRAINT uq_candidate_activity_summary_scope_policy
                            UNIQUE (
                                candidate_id,
                                visibility_scope_hash,
                                content_policy_version
                            ),
                        CONSTRAINT ck_candidate_activity_summary_lease_pair
                            CHECK (
                                (
                                    generation_lease_token IS NULL
                                    AND generation_lease_expires_at IS NULL
                                )
                                OR (
                                    generation_lease_token IS NOT NULL
                                    AND generation_lease_expires_at IS NOT NULL
                                )
                        )
                    )
                    """
                )
            )
            await connection.execute(
                text("INSERT INTO candidates (id) VALUES (1), (2)")
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO candidate_activity_summaries (
                        candidate_id,
                        summary,
                        model,
                        input_hash,
                        source_version,
                        visibility_scope_hash,
                        content_policy_version,
                        source_manifest,
                        generated_at
                    )
                    VALUES
                        (
                            1, 'scope A', 'test-model', :source_a, :source_a,
                            :scope_a, :current_policy,
                            '{"content_policy_version":
                                "candidate-summary-no-finance-v3",
                              "sources": []}'::jsonb,
                            now()
                        ),
                        (
                            1, 'scope B', 'test-model', :source_b, :source_b,
                            :scope_b, :current_policy,
                            '{"content_policy_version":
                                "candidate-summary-no-finance-v3",
                              "sources": []}'::jsonb,
                            now()
                        ),
                        (
                            2, 'old unsafe prose', 'old-model', :source_a, :source_a,
                            'legacy-unscoped', 'legacy-unscoped',
                            '{"raw": "must be removed"}'::jsonb,
                            now()
                        )
                    """
                ),
                {
                    "scope_a": scope_a,
                    "scope_b": scope_b,
                    "source_a": source_a,
                    "source_b": source_b,
                    "current_policy": current_policy,
                },
            )

            original_op = migration.op

            def run_upgrade(sync_connection) -> None:
                migration.op = Operations(
                    MigrationContext.configure(sync_connection)
                )
                try:
                    migration.upgrade()
                finally:
                    migration.op = original_op

            await connection.run_sync(run_upgrade)

            scoped_rows = (
                await connection.execute(
                    text(
                        """
                        SELECT visibility_scope_hash, source_version
                        FROM candidate_activity_summaries
                        WHERE candidate_id = 1
                        ORDER BY visibility_scope_hash
                        """
                    )
                )
            ).all()
            assert scoped_rows == [(scope_a, source_a), (scope_b, source_b)]

            legacy_row = (
                await connection.execute(
                    text(
                        """
                        SELECT visibility_scope_hash,
                               content_policy_version,
                               source_version,
                               source_manifest,
                               generation_lease_token,
                               generation_lease_expires_at
                        FROM candidate_activity_summaries
                        WHERE candidate_id = 2
                        """
                    )
                )
            ).one()
            assert legacy_row.visibility_scope_hash == "legacy-unscoped"
            assert legacy_row.content_policy_version == "legacy-unscoped"
            assert legacy_row.source_version is None
            assert legacy_row.source_manifest == {}
            assert legacy_row.generation_lease_token is None
            assert legacy_row.generation_lease_expires_at is None
        finally:
            # All fixture DDL and migration effects are isolated in this
            # transaction; rollback also removes the temporary schema.
            await transaction.rollback()
