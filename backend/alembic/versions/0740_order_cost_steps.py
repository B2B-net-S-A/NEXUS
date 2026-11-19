"""Koszt zamówienia od dnia zmiany stawki Partnera.

Revision ID: 0740_order_cost_steps
Revises: 0739_contract_rate_documents

Tabele ``client_order_cost_steps`` (części kosztu zamówienia) i
``client_order_cost_reviews`` („Zostaw” na liście Finansów). DDL ma jedno
źródło (``app/services/order_cost_steps_schema.py``); entrypoint wykonuje je
przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import order_cost_steps_schema as schema

revision = "0740_order_cost_steps"
down_revision = "0739_contract_rate_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
