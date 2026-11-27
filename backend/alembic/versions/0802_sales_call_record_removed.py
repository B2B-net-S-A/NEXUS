"""Sprzedaż → Dzwonienie: „Usuń z listy” z akcji zbiorczych Tabeli (miękkie usunięcie).

Revision ID: 0802_sales_call_record_removed
Revises: 0801_b2b_krz_check

Decyzja Artura z 27.11.2026 (wariant A): ``sales_call_records.removed_at`` i kto usunął.
Rekord znika z kolejki i Tabeli, „Cofnij” go przywraca, a bramka importu dalej go widzi.
DDL w ``app/services/sales_schema.py`` (``CALL_RECORD_REMOVAL_DDL``); ``entrypoint.sh``
wpina tę samą listę.
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0802_sales_call_record_removed"
down_revision = "0801_b2b_krz_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.CALL_RECORD_REMOVAL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.CALL_RECORD_REMOVAL_DOWNGRADE_DDL:
        op.execute(stmt)
