"""Persist daily Analytics v1 shadow parity evidence.

Revision ID: 0165_analytics_shadow_comparisons
Revises: 0164_analytics_v1_kpi_defaults
Create Date: 2026-07-14

The table is additive and intentionally survives runtime rollback. One row per
Warsaw business day and metric is updated by the shadow loop, so a seven-day
parity window can be proven from database evidence instead of log sampling.
"""

from alembic import op


revision = "0165_analytics_shadow_comparisons"
down_revision = "0164_analytics_v1_kpi_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Correct first-touch precedence on already-migrated databases: an explicit
    # source event is authoritative; Candidate.source is fallback only when no
    # event exists for that candidate.
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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_shadow_comparisons (
            id BIGSERIAL PRIMARY KEY,
            observed_on DATE NOT NULL,
            module_key VARCHAR(64) NOT NULL,
            metric_key VARCHAR(128) NOT NULL,
            metric_version VARCHAR(32) NOT NULL,
            period_start TIMESTAMPTZ NOT NULL,
            period_end TIMESTAMPTZ NOT NULL,
            legacy_value NUMERIC(24, 6) NULL,
            analytics_value NUMERIC(24, 6) NULL,
            absolute_diff NUMERIC(24, 6) NULL,
            status VARCHAR(24) NOT NULL,
            details JSONB NOT NULL DEFAULT '{}'::jsonb,
            first_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_analytics_shadow_period CHECK (period_start < period_end),
            CONSTRAINT ck_analytics_shadow_status CHECK (
                status IN ('identical', 'mismatch', 'unavailable')
            ),
            CONSTRAINT uq_analytics_shadow_daily_metric UNIQUE (
                observed_on, module_key, metric_key, metric_version
            )
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_shadow_status_day "
        "ON analytics_shadow_comparisons (status, observed_on DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_shadow_module_day "
        "ON analytics_shadow_comparisons (module_key, observed_on DESC)"
    )


def downgrade() -> None:
    # Analytics rollback is runtime-only during the evidence/retention window.
    pass
