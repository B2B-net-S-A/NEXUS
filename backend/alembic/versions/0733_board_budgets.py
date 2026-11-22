"""Budżet Rady nadzorczej: plan miesięczny sprzedaży i kosztów (R3).

Revision ID: 0733_board_budgets
Revises: 0732_cpro_bot_runs

Tabele ``board_budgets`` i ``board_budget_lines``. DDL ma jedno źródło
(``app/services/board_budget_schema.py``); entrypoint wykonuje je przy każdym
starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import board_budget_schema as schema

revision = "0733_board_budgets"
down_revision = "0732_cpro_bot_runs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
