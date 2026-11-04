"""Dolna granica budżetu rekrutacji („od–do”, 06.10.2026).

Revision ID: 0420_job_budget_hourly_min
Revises: 0419_md_rate_scale_pool_breakdown

``jobs.rate_budget_hourly_min`` trzyma „od” z przedziału „60–80 zł/h”.
Budżetem dla całej logiki zostaje ``rate_budget_hourly`` (góra); dolna
granica jest tylko do wyświetlania. DDL ma jedno źródło z entrypointem
(``job_budget_range.COLUMN_DDL``).
"""

from alembic import op

from app.services import job_budget_range

revision = "0420_job_budget_hourly_min"
down_revision = "0419_md_rate_scale_pool_breakdown"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(job_budget_range.COLUMN_DDL)


def downgrade() -> None:
    # „Od” istnieje tylko w tej kolumnie — downgrade przy danych by je skasował.
    op.execute(
        """DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM jobs WHERE rate_budget_hourly_min IS NOT NULL) THEN
                RAISE EXCEPTION 'Downgrade 0420 odmawia: jobs ma wpisy rate_budget_hourly_min.';
            END IF;
        END $$"""
    )
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS rate_budget_hourly_min")
