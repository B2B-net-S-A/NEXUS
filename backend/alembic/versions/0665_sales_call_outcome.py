"""Sprzedaż: wynik rozmowy w aktywności i sprzeciw wobec kontaktu.

Revision ID: 0665_sales_call_outcome
Revises: 0664_dl_alert_invoice_no_line

DDL w ``app/services/sales_schema.py``; ``entrypoint.sh`` wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0665_sales_call_outcome"
down_revision = "0664_dl_alert_invoice_no_line"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CALL_OUTCOME_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.CALL_OUTCOME_DOWNGRADE_DDL:
        op.execute(stmt)
