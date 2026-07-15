"""Canonical analytics v1 views, indexes and cutover storage.

Revision ID: 0162_analytics_v1_foundation
Revises: 0160_contract_document_type_order
Create Date: 2026-07-14

The migration is additive.  Ordinary views provide one shared definition for
current pipeline, first milestones/credit attribution and first-touch source.
Legacy-only history can be copied into immutable snapshots without mixing it
with live ATS rows after a module's explicit cutover date.
"""

from alembic import op


revision = "0162_analytics_v1_foundation"
down_revision = "0160_contract_document_type_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # First activation timestamp cannot be reconstructed reliably for legacy
    # orders.  Existing active rows intentionally remain NULL/quality=partial.
    op.execute(
        "ALTER TABLE client_orders "
        "ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_orders_filled_at "
        "ON client_orders (filled_at) WHERE filled_at IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_adjustments (
            id BIGSERIAL PRIMARY KEY,
            adjustment_date DATE NOT NULL,
            category VARCHAR(64) NOT NULL,
            description TEXT NOT NULL,
            amount NUMERIC(14, 2) NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
            amount_pln NUMERIC(14, 2) NULL,
            fx_rate NUMERIC(18, 8) NULL,
            fx_date DATE NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            created_by_user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            approved_by_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE RESTRICT,
            approved_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_financial_adjustments_nonzero CHECK (amount <> 0),
            CONSTRAINT ck_financial_adjustments_currency CHECK (
                currency = upper(currency) AND char_length(currency) = 3
            ),
            CONSTRAINT ck_financial_adjustments_status CHECK (
                status IN ('draft', 'approved')
            ),
            CONSTRAINT ck_financial_adjustments_approval CHECK (
                status = 'draft'
                OR (
                    approved_by_user_id IS NOT NULL
                    AND approved_at IS NOT NULL
                    AND amount_pln IS NOT NULL
                )
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_status_date "
        "ON financial_adjustments (status, adjustment_date)"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_metric_snapshots (
            id BIGSERIAL PRIMARY KEY,
            snapshot_key VARCHAR(255) NOT NULL UNIQUE,
            metric_key VARCHAR(128) NOT NULL,
            metric_version VARCHAR(32) NOT NULL,
            scope VARCHAR(64) NOT NULL,
            scope_ref VARCHAR(128) NULL,
            period_start TIMESTAMPTZ NOT NULL,
            period_end TIMESTAMPTZ NOT NULL,
            timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Warsaw',
            data JSONB NOT NULL,
            source VARCHAR(64) NOT NULL,
            source_ref VARCHAR(255) NULL,
            checksum CHAR(64) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_analytics_snapshot_period CHECK (period_start < period_end),
            CONSTRAINT ck_analytics_snapshot_checksum CHECK (
                checksum ~ '^[0-9a-f]{64}$'
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_snapshots_metric_period "
        "ON analytics_metric_snapshots (metric_key, period_start, period_end)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_snapshots_scope "
        "ON analytics_metric_snapshots (scope, scope_ref)"
    )

    # Snapshots are append-only. Corrections are a new snapshot_key/checksum;
    # this makes cutover history auditable rather than silently mutable.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION reject_analytics_snapshot_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'analytics_metric_snapshots is append-only';
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_analytics_snapshots_immutable "
        "ON analytics_metric_snapshots"
    )
    op.execute(
        """
        CREATE TRIGGER trg_analytics_snapshots_immutable
        BEFORE UPDATE OR DELETE ON analytics_metric_snapshots
        FOR EACH ROW EXECUTE FUNCTION reject_analytics_snapshot_mutation()
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_cutovers (
            module_key VARCHAR(64) PRIMARY KEY,
            cutover_at TIMESTAMPTZ NOT NULL,
            timezone VARCHAR(64) NOT NULL DEFAULT 'Europe/Warsaw',
            legacy_source VARCHAR(64) NOT NULL DEFAULT 'dynareporter',
            created_by_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            updated_by_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW analytics_latest_candidate_stages AS
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
            cs.candidate_id,
            cs.job_id,
            cs.stage::text AS stage,
            cs.moved_at,
            cs.moved_by,
            cs.id AS candidate_stage_id
        FROM candidate_stages cs
        ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
        """
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW analytics_first_candidate_milestones AS
        WITH first_moves AS (
            SELECT DISTINCT ON (cs.candidate_id, cs.job_id, cs.stage)
                cs.candidate_id,
                cs.job_id,
                cs.stage::text AS stage,
                cs.moved_at AS reached_at,
                cs.moved_by AS milestone_user_id,
                cs.id AS candidate_stage_id
            FROM candidate_stages cs
            WHERE cs.stage::text IN (
                'verified', 'cv_sent', 'interview', 'client_interview', 'hired'
            )
            ORDER BY cs.candidate_id, cs.job_id, cs.stage,
                     cs.moved_at ASC, cs.id ASC
        ), verifier AS (
            SELECT candidate_id, job_id, milestone_user_id AS verifier_user_id
            FROM first_moves
            WHERE stage = 'verified'
        )
        SELECT
            fm.candidate_id,
            fm.job_id,
            fm.stage,
            fm.reached_at,
            fm.milestone_user_id,
            coalesce(v.verifier_user_id, fm.milestone_user_id)
                AS credited_user_id,
            fm.candidate_stage_id
        FROM first_moves fm
        LEFT JOIN verifier v USING (candidate_id, job_id)
        """
    )

    op.execute(
        """
        CREATE OR REPLACE VIEW analytics_candidate_first_sources AS
        WITH first_event AS (
            SELECT DISTINCT ON (candidate_id)
                candidate_id,
                channel::text AS source,
                captured_at AS touched_at
            FROM candidate_source_events
            ORDER BY candidate_id, captured_at ASC, id ASC
        )
        SELECT
            c.id AS candidate_id,
            coalesce(
                first_event.source,
                CASE
                    WHEN c.source_enum IS NOT NULL THEN c.source_enum::text
                    WHEN lower(trim(c.source)) IN (
                        'linkedin', 'pracuj', 'jjit', 'referral',
                        'database', 'manual'
                    ) THEN lower(trim(c.source))
                    WHEN nullif(trim(c.source), '') IS NULL THEN 'unknown'
                    ELSE 'other'
                END
            ) AS source,
            coalesce(first_event.touched_at, c.created_at) AS first_touch_at
        FROM candidates c
        LEFT JOIN first_event ON first_event.candidate_id = c.id
        """
    )

    # Build read-path indexes without blocking ATS writes.  Equality columns
    # lead range columns; INCLUDE keeps common aggregations index-only.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_candidate_stages_pair_time "
            "ON candidate_stages (candidate_id, job_id, moved_at DESC, id DESC) "
            "INCLUDE (stage, moved_by)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_candidate_stages_milestone_time "
            "ON candidate_stages (stage, moved_at, candidate_id, job_id) "
            "INCLUDE (moved_by, id) WHERE stage IN "
            "('verified', 'cv_sent', 'interview', 'client_interview', 'hired')"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_calls_completed_time "
            "ON calls ((coalesce(started_at, created_at)), user_id) "
            "INCLUDE (direction, duration_seconds) WHERE status = 'completed'"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_calls_user_completed_time "
            "ON calls (user_id, (coalesce(started_at, created_at))) "
            "INCLUDE (direction, duration_seconds) "
            "WHERE status = 'completed' AND user_id IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_source_events_candidate_time "
            "ON candidate_source_events (candidate_id, captured_at, id) "
            "INCLUDE (channel)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_candidates_creator_time "
            "ON candidates (created_by, created_at) WHERE created_by IS NOT NULL"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_analytics_contracts_effective_dates "
            "ON contracts (start_date, end_date) "
            "WHERE status IN ('active', 'ending')"
        )


def downgrade() -> None:
    # Rollback during the compatibility window is runtime-only (`live` ->
    # `shadow`) and must never delete analytics history or columns.  Schema
    # cleanup is intentionally deferred until the retention window and restore
    # drill have completed.
    pass
