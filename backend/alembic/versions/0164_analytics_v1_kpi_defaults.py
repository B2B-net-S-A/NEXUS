"""Seed canonical Analytics v1 KPI target defaults.

Revision ID: 0164_analytics_v1_kpi_defaults
Revises: 0162_analytics_v1_foundation
Create Date: 2026-07-14

The insert is additive and preserves any target already configured by an
administrator. Legacy KPI identifiers remain readable during the adapter
window, but v2 resolves the canonical key first.
"""

from alembic import op


revision = "0164_analytics_v1_kpi_defaults"
down_revision = "0162_analytics_v1_foundation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO kpi_role_defaults
            (role, kpi_id, target_value, created_at, updated_at)
        VALUES
            ('sourcer', 'calls_daily', 15, now(), now()),
            ('recruiter', 'calls_daily', 15, now(), now()),
            ('tac', 'calls_daily', 15, now(), now()),
            ('sourcer', 'verifications_daily', 4, now(), now()),
            ('recruiter', 'verifications_daily', 4, now(), now()),
            ('tac', 'verifications_daily', 4, now(), now())
        ON CONFLICT (role, kpi_id) DO NOTHING
        """
    )


def downgrade() -> None:
    # Rollback-window migrations are additive. Do not delete potentially
    # administrator-customized targets on downgrade.
    pass
