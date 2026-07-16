"""Snapshoty metryk + rejestr cutoverów (plan PR 7).

Lustro w backend/entrypoint.sh (multi-head trap).

Revision ID: 0177_analytics_snapshots_cutovers
Revises: 0176_finance_filled_at_adjustments
"""

from alembic import op

revision = "0177_analytics_snapshots_cutovers"
down_revision = "0176_finance_filled_at_adjustments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_metric_snapshots (
            id           SERIAL PRIMARY KEY,
            module       VARCHAR(50) NOT NULL,
            metric       VARCHAR(80) NOT NULL,
            period_label VARCHAR(20) NOT NULL,
            value        JSONB NOT NULL,
            source       VARCHAR(40) NOT NULL DEFAULT 'dynareporter',
            checksum     VARCHAR(64) NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_analytics_snapshot
                UNIQUE (module, metric, period_label, source)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_snapshots_module "
        "ON analytics_metric_snapshots (module, period_label)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS analytics_cutovers (
            id            SERIAL PRIMARY KEY,
            module        VARCHAR(50) NOT NULL UNIQUE,
            cutover_date  DATE NOT NULL,
            legacy_source VARCHAR(40) NOT NULL DEFAULT 'dynareporter',
            notes         TEXT,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS analytics_metric_snapshots")
    op.execute("DROP TABLE IF EXISTS analytics_cutovers")
