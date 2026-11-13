"""Rozliczenia klientów E5.1: koszty integracji konsultanta ze zgodą DL-a.

Revision ID: 0687_settlement_integration_costs
Revises: 0686_autofill_gaps_round4

SQL i powody: ``app/services/client_settlements_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import client_settlements_schema as schema

revision = "0687_settlement_integration_costs"
down_revision = "0686_autofill_gaps_round4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.INTEGRATION_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_settlement_integration_costs CASCADE")
