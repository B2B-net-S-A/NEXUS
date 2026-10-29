"""Sprzedaż: historia zmian szansy (kto, kiedy, pole, stara i nowa wartość).

Revision ID: 0617_sales_opportunity_events
Revises: 0616_autofill_more_reasons

SQL i powody: ``app/services/sales_schema.py`` (``HISTORY_DDL``; to samo
źródło czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0617_sales_opportunity_events"
down_revision = "0616_autofill_more_reasons"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.HISTORY_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.HISTORY_DOWNGRADE_DDL:
        op.execute(stmt)
