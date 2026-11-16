"""Kroki stawki przychodowej linii zamówienia (aneks stawki klienta).

Revision ID: 0724_order_revenue_steps
Revises: 0723_b2b_annex_custom

Tabela ``client_order_revenue_steps`` — stawka przychodowa zamówienia od dnia
aneksu. DDL ma jedno źródło (``app/services/order_revenue_steps_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import order_revenue_steps_schema as schema

revision = "0724_order_revenue_steps"
down_revision = "0723_b2b_annex_custom"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
