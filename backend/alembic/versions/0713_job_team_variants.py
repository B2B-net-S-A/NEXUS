"""Zespół dla klienta: gotowe składy zatwierdzone przez DL-a (15.11.2026).

Revision ID: 0713_job_team_variants
Revises: 0712_client_reports

Kolumny ``job_teams.variants``, ``variants_approved_at``, ``variants_approved_by``.
SQL i powód: ``app/services/job_team_schema.py``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_team_schema as schema

revision = "0713_job_team_variants"
down_revision = "0712_client_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.VARIANTS_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.VARIANTS_DOWNGRADE_DDL:
        op.execute(statement)
