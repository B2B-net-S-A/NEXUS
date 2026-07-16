"""Analytics v1 — milestone `acceptance` w kanonicznym view (plan PR 4).

Panel KPI (`kpi_panel`/`kpi_team`) liczy też `akceptacje_month` — żeby
przepiąć atrybucję na kanoniczny view bez utraty tej metryki, view
``analytics_first_milestones`` obejmuje dodatkowo stage 'acceptance'.
Indeks partial dostaje nową nazwę (predykatu nie da się ALTER-ować);
stary jest usuwany.

Lustro w backend/entrypoint.sh _COLUMN_STATEMENTS (multi-head trap).

Revision ID: 0175_analytics_milestones_acceptance
Revises: 0174_analytics_v1_foundation
"""

from alembic import op

revision = "0175_analytics_milestones_acceptance"
down_revision = "0174_analytics_v1_foundation"
branch_labels = None
depends_on = None

MILESTONE_STAGES = (
    "'verified', 'cv_sent', 'interview', 'client_interview', 'acceptance', 'hired'"
)

VIEW_SQL = f"""
    CREATE OR REPLACE VIEW analytics_first_milestones AS
    SELECT
        candidate_id,
        job_id,
        stage,
        moved_at AS first_reached_at,
        moved_by AS first_moved_by,
        id AS candidate_stage_id
    FROM (
        SELECT
            cs.candidate_id,
            cs.job_id,
            cs.stage,
            cs.moved_at,
            cs.moved_by,
            cs.id,
            ROW_NUMBER() OVER (
                PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                ORDER BY cs.moved_at ASC, cs.id ASC
            ) AS rn
        FROM candidate_stages cs
        WHERE cs.stage IN ({MILESTONE_STAGES})
    ) ranked
    WHERE rn = 1
"""

OLD_VIEW_SQL = """
    CREATE OR REPLACE VIEW analytics_first_milestones AS
    SELECT
        candidate_id,
        job_id,
        stage,
        moved_at AS first_reached_at,
        moved_by AS first_moved_by,
        id AS candidate_stage_id
    FROM (
        SELECT
            cs.candidate_id,
            cs.job_id,
            cs.stage,
            cs.moved_at,
            cs.moved_by,
            cs.id,
            ROW_NUMBER() OVER (
                PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                ORDER BY cs.moved_at ASC, cs.id ASC
            ) AS rn
        FROM candidate_stages cs
        WHERE cs.stage IN (
            'verified', 'cv_sent', 'interview', 'client_interview', 'hired'
        )
    ) ranked
    WHERE rn = 1
"""


def upgrade() -> None:
    op.execute(VIEW_SQL)
    op.execute("DROP INDEX IF EXISTS ix_analytics_cs_stage_first")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_cs_stage_first_v2 "
        "ON candidate_stages (stage, candidate_id, job_id, moved_at ASC, id ASC) "
        f"WHERE stage IN ({MILESTONE_STAGES})"
    )


def downgrade() -> None:
    op.execute(OLD_VIEW_SQL)
    op.execute("DROP INDEX IF EXISTS ix_analytics_cs_stage_first_v2")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_analytics_cs_stage_first "
        "ON candidate_stages (stage, candidate_id, job_id, moved_at ASC, id ASC) "
        "WHERE stage IN "
        "('verified', 'cv_sent', 'interview', 'client_interview', 'hired')"
    )
