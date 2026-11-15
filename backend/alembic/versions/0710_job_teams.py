"""Zespół dla klienta: kilka rekrutacji jednego klienta i jeden link (15.11.2026).

Revision ID: 0710_job_teams
Revises: 0709_sales_invoice_templates

Tabele ``job_teams``, ``job_team_selections`` i kolumna ``jobs.team_id``. SQL
i powód: ``app/services/job_team_schema.py``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import job_team_schema as schema

revision = "0710_job_teams"
down_revision = "0709_sales_invoice_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
