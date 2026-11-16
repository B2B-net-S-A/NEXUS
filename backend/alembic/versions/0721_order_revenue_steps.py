"""Kroki stawki przychodowej linii zamówienia (aneks stawki klienta).

Revision ID: 0721_order_revenue_steps
Revises: 0720_finance_archive

Tabela ``client_order_revenue_steps`` — stawka przychodowa zamówienia od dnia
aneksu. DDL ma jedno źródło (``app/services/order_revenue_steps_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import order_revenue_steps_schema as schema

revision = "0721_order_revenue_steps"
down_revision = "0720_finance_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
