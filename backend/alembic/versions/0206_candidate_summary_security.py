"""Scope-aware, no-finance candidate activity-summary cache.

Existing 0204 rows were generated for an unknown visibility scope and under a
policy that included financial data.  They receive the explicit
``legacy-unscoped`` scope/policy and can never match the application query.

The cache becomes one row per (candidate, visibility scope, content policy).
Nullable output fields let a row act as a short generation lease; the service
commits that lease before calling the provider and publishes through a CAS
token afterwards.

Revision ID: 0206_candidate_summary_security
Revises: 0205_candidate_profile_facts
"""

from alembic import op

revision = "0206_candidate_summary_security"
down_revision = "0205_candidate_profile_facts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidate_activity_summaries
            ALTER COLUMN summary DROP NOT NULL,
            ALTER COLUMN generated_at DROP NOT NULL,
            ADD COLUMN IF NOT EXISTS source_version VARCHAR(64) NULL,
            ADD COLUMN IF NOT EXISTS visibility_scope_hash VARCHAR(64)
                NOT NULL DEFAULT 'legacy-unscoped',
            ADD COLUMN IF NOT EXISTS content_policy_version VARCHAR(64)
                NOT NULL DEFAULT 'legacy-unscoped',
            ADD COLUMN IF NOT EXISTS source_manifest JSONB
                NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS generation_lease_token VARCHAR(36) NULL,
            ADD COLUMN IF NOT EXISTS generation_lease_expires_at
                TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        UPDATE candidate_activity_summaries
        SET visibility_scope_hash = 'legacy-unscoped',
            content_policy_version = 'legacy-unscoped',
            source_version = NULL,
            source_manifest = '{}'::jsonb,
            generation_lease_token = NULL,
            generation_lease_expires_at = NULL
        WHERE visibility_scope_hash = 'legacy-unscoped'
           OR content_policy_version = 'legacy-unscoped'
        """
    )
    op.execute(
        "ALTER TABLE candidate_activity_summaries "
        "DROP CONSTRAINT IF EXISTS uq_candidate_activity_summary"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'uq_candidate_activity_summary_scope_policy'
                  AND conrelid = 'candidate_activity_summaries'::regclass
            ) THEN
                ALTER TABLE candidate_activity_summaries
                    ADD CONSTRAINT uq_candidate_activity_summary_scope_policy
                    UNIQUE (
                        candidate_id,
                        visibility_scope_hash,
                        content_policy_version
                    );
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'ck_candidate_activity_summary_lease_pair'
                  AND conrelid = 'candidate_activity_summaries'::regclass
            ) THEN
                ALTER TABLE candidate_activity_summaries
                    ADD CONSTRAINT ck_candidate_activity_summary_lease_pair
                    CHECK (
                        (generation_lease_token IS NULL
                         AND generation_lease_expires_at IS NULL)
                        OR
                        (generation_lease_token IS NOT NULL
                         AND generation_lease_expires_at IS NOT NULL)
                    );
            END IF;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            ix_candidate_activity_summaries_scope_policy
        ON candidate_activity_summaries (
            candidate_id,
            visibility_scope_hash,
            content_policy_version
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            ix_candidate_activity_summaries_lease_expires_at
        ON candidate_activity_summaries (generation_lease_expires_at)
        WHERE generation_lease_expires_at IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS candidate_source_identity_reviews (
            id                  SERIAL PRIMARY KEY,
            candidate_id        INTEGER NOT NULL
                                    REFERENCES candidates(id) ON DELETE CASCADE,
            source_kind         VARCHAR(24) NOT NULL,
            source_id           BIGINT NOT NULL,
            decision            VARCHAR(32) NOT NULL,
            provenance          VARCHAR(80) NOT NULL,
            detector_version    VARCHAR(64) NOT NULL,
            evidence            JSONB NOT NULL DEFAULT '{}'::jsonb,
            reviewed_by_id      INTEGER NULL
                                    REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at         TIMESTAMPTZ NOT NULL,
            override_reason     TEXT NULL,
            override_by_id      INTEGER NULL
                                    REFERENCES users(id) ON DELETE SET NULL,
            override_at         TIMESTAMPTZ NULL,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_candidate_source_identity_review
                UNIQUE (candidate_id, source_kind, source_id),
            CONSTRAINT ck_candidate_source_identity_review_kind
                CHECK (
                    source_kind IN (
                        'note', 'document', 'legacy_cv', 'talent_radar_cv'
                    )
                ),
            CONSTRAINT ck_candidate_source_identity_review_decision
                CHECK (
                    decision IN (
                        'confirmed_match',
                        'confirmed_mismatch',
                        'inconclusive'
                    )
                ),
            CONSTRAINT ck_candidate_source_identity_review_override
                CHECK (
                    (
                        override_at IS NULL
                        AND override_by_id IS NULL
                        AND override_reason IS NULL
                    )
                    OR
                    (
                        override_at IS NOT NULL
                        AND override_by_id IS NOT NULL
                        AND override_reason IS NOT NULL
                        AND length(btrim(override_reason)) >= 3
                    )
                )
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_candidate_source_identity_reviews_candidate
        ON candidate_source_identity_reviews (candidate_id)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS
            ix_candidate_source_identity_reviews_quarantine
        ON candidate_source_identity_reviews (
            candidate_id,
            source_kind,
            source_id
        )
        WHERE decision = 'confirmed_mismatch' AND override_at IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_source_identity_reviews")
    # Lease placeholders are non-user data and cannot satisfy the old NOT NULL
    # contract.  Scoped duplicate prose is a regenerable cache; keep the newest
    # row per candidate before restoring the original one-row constraint.
    op.execute("DELETE FROM candidate_activity_summaries WHERE summary IS NULL")
    op.execute(
        """
        DELETE FROM candidate_activity_summaries older
        USING candidate_activity_summaries newer
        WHERE older.candidate_id = newer.candidate_id
          AND (
              older.generated_at < newer.generated_at
              OR (
                  older.generated_at = newer.generated_at
                  AND older.id < newer.id
              )
          )
        """
    )
    op.execute("DROP INDEX IF EXISTS ix_candidate_activity_summaries_lease_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_candidate_activity_summaries_scope_policy")
    op.execute(
        "ALTER TABLE candidate_activity_summaries "
        "DROP CONSTRAINT IF EXISTS ck_candidate_activity_summary_lease_pair"
    )
    op.execute(
        "ALTER TABLE candidate_activity_summaries "
        "DROP CONSTRAINT IF EXISTS uq_candidate_activity_summary_scope_policy"
    )
    op.execute(
        """
        ALTER TABLE candidate_activity_summaries
            DROP COLUMN IF EXISTS generation_lease_expires_at,
            DROP COLUMN IF EXISTS generation_lease_token,
            DROP COLUMN IF EXISTS source_manifest,
            DROP COLUMN IF EXISTS content_policy_version,
            DROP COLUMN IF EXISTS visibility_scope_hash,
            DROP COLUMN IF EXISTS source_version,
            ALTER COLUMN summary SET NOT NULL,
            ALTER COLUMN generated_at SET NOT NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_activity_summaries
            ADD CONSTRAINT uq_candidate_activity_summary UNIQUE (candidate_id)
        """
    )
