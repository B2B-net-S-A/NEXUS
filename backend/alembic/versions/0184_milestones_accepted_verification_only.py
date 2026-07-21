"""Analytics — kamień milowy `verified` liczy się tylko po akceptacji (M7-P0.8).

``analytics_first_milestones`` liczyła KAŻDY wiersz ``candidate_stages`` ze
``stage='verified'`` niezależnie od ``verification_status``. Ruch na `verified`
z rate'm > Job.salary_max zapisuje wiersz natychmiast (``status=pending``,
migracja 0056), a odrzucenie (``status=rejected``) zostawia ten wiersz na
`verified` (zachowanie historii). Efekt (M7-P0.8):

- odrzucona/oczekująca próba podbijała KPI (`first_verifications`), oraz
- kotwiczyła kredyt: `kpi_panel` ustawia `credit_user` = pierwszy `verified`
  (rn=1), więc `pending`/`rejected` weryfikator przejmował zasługę za
  późniejsze kamienie (cv_sent/interview/hired) — premia za byle-jakie wysyłki.

Fix: w widoku licz `verified` tylko gdy `verification_status='active'`
(zaakceptowana). Pozostałe stage'y mają default 'active', więc predykat
ich nie dotyka. Idempotentny CREATE OR REPLACE — brak zmiany schematu,
tylko definicji widoku.

Lustro w backend/entrypoint.sh (multi-head trap — prod alembic osierocony).

Revision ID: 0184_milestones_accepted_verification_only
Revises: 0183_invite_link_token_hash_encrypt
"""

from alembic import op

revision = "0184_milestones_accepted_verification_only"
down_revision = "0183_invite_link_token_hash_encrypt"
branch_labels = None
depends_on = None

MILESTONE_STAGES = (
    "'verified', 'cv_sent', 'interview', 'client_interview', 'acceptance', 'hired'"
)

# Nowa definicja: `verified` tylko z verification_status='active'.
NEW_VIEW_SQL = f"""
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
          AND (cs.stage <> 'verified' OR cs.verification_status = 'active')
    ) ranked
    WHERE rn = 1
"""

# Poprzednia (0175): bez filtra verification_status.
OLD_VIEW_SQL = f"""
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


def upgrade() -> None:
    op.execute(NEW_VIEW_SQL)


def downgrade() -> None:
    op.execute(OLD_VIEW_SQL)
