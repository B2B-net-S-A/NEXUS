"""Sprawozdania roczne dla Rady: bilans i RZiS z e-Sprawozdań (R4).

Revision ID: 0734_board_statements
Revises: 0733_board_budgets

Tabela ``board_financial_statements``. DDL ma jedno źródło
(``app/services/board_statements_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import board_statements_schema as schema

revision = "0734_board_statements"
down_revision = "0733_board_budgets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
