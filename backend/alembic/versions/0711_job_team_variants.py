"""Zespół dla klienta: gotowe składy zatwierdzone przez DL-a (15.11.2026).

Revision ID: 0711_job_team_variants
Revises: 0710_job_teams

Kolumny ``job_teams.variants``, ``variants_approved_at``, ``variants_approved_by``.
SQL i powód: ``app/services/job_team_schema.py``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_team_schema as schema

revision = "0711_job_team_variants"
down_revision = "0710_job_teams"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.VARIANTS_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.VARIANTS_DOWNGRADE_DDL:
        op.execute(statement)
