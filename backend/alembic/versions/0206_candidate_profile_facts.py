"""Typed candidate profile facts: languages and global B2B rate.

Revision ID: 0206_candidate_profile_facts
Revises: 0205_client_directory_portfolio
Create Date: 2026-07-30

The migration is additive for language facts and OCC metadata. The existing
hourly rate changes from INTEGER to NUMERIC(10,2); no value or currency is
converted. Legacy ``candidates.languages`` JSONB is intentionally not copied
here: the separately operated backfill supports dry-run, checkpoints and a
parity report.
"""

from alembic import op

revision = "0206_candidate_profile_facts"
down_revision = "0205_client_directory_portfolio"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidates
            ADD COLUMN IF NOT EXISTS languages_version
                INTEGER NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS profile_rate_version
                INTEGER NOT NULL DEFAULT 1,
            ADD COLUMN IF NOT EXISTS profile_rate_updated_at
                TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidates
        ALTER COLUMN expected_rate_hourly
        TYPE NUMERIC(10,2)
        USING expected_rate_hourly::numeric(10,2)
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_languages (
            id                  SERIAL PRIMARY KEY,
            candidate_id        INTEGER NOT NULL
                                    REFERENCES candidates(id) ON DELETE CASCADE,
            language_code       VARCHAR(16) NOT NULL,
            language_name       VARCHAR(100) NOT NULL,
            cefr_level          VARCHAR(2) NULL,
            is_native           BOOLEAN NOT NULL DEFAULT FALSE,
            is_level_unknown    BOOLEAN NOT NULL DEFAULT TRUE,
            provenance          VARCHAR(32) NOT NULL DEFAULT 'unknown',
            manual_lock         BOOLEAN NOT NULL DEFAULT FALSE,
            source_ref          VARCHAR(255) NULL,
            version             INTEGER NOT NULL DEFAULT 1,
            deleted_at          TIMESTAMPTZ NULL,
            created_by          INTEGER NULL
                                    REFERENCES users(id) ON DELETE SET NULL,
            updated_by          INTEGER NULL
                                    REFERENCES users(id) ON DELETE SET NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_languages_candidate_code
                UNIQUE (candidate_id, language_code),
            CONSTRAINT ck_candidate_languages_code
                CHECK (language_code ~ '^[a-z][a-z0-9-]{1,15}$'),
            CONSTRAINT ck_candidate_languages_cefr
                CHECK (
                    cefr_level IS NULL
                    OR cefr_level IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')
                ),
            CONSTRAINT ck_candidate_languages_proficiency_state
                CHECK (
                    (
                        is_native IS TRUE
                        AND is_level_unknown IS FALSE
                        AND cefr_level IS NULL
                    )
                    OR (
                        is_native IS FALSE
                        AND is_level_unknown IS TRUE
                        AND cefr_level IS NULL
                    )
                    OR (
                        is_native IS FALSE
                        AND is_level_unknown IS FALSE
                        AND cefr_level IS NOT NULL
                    )
                ),
            CONSTRAINT ck_candidate_languages_provenance
                CHECK (
                    provenance IN (
                        'manual', 'cv', 'traffit', 'talent_radar',
                        'csv', 'legacy', 'unknown'
                    )
                ),
            CONSTRAINT ck_candidate_languages_version_positive
                CHECK (version > 0)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_languages_candidate_id "
        "ON candidate_languages (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_languages_candidate_active "
        "ON candidate_languages (candidate_id, language_code) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_languages")
    op.execute(
        """
        ALTER TABLE candidates
        ALTER COLUMN expected_rate_hourly
        TYPE INTEGER
        USING round(expected_rate_hourly)::integer
        """
    )
    op.execute(
        """
        ALTER TABLE candidates
            DROP COLUMN IF EXISTS profile_rate_updated_at,
            DROP COLUMN IF EXISTS profile_rate_version,
            DROP COLUMN IF EXISTS languages_version
        """
    )
