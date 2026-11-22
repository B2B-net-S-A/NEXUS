"""Korekta zbiorcza rabatu od obrotu: kolumna ``collective_correction`` i CHECK korekty.

Revision ID: 0749_rebate_collective_correction
Revises: 0748_drop_invoices_register

Decyzja Artura z 16.11.2026: za miesiąc przekroczenia progu rabatu jedna korekta
zbiorcza (art. 106j ust. 3) wskazuje wszystkie faktury miesiąca z KSeF. DDL ma
jedno źródło (``app/services/client_invoice_collective_correction_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_invoice_collective_correction_schema as schema

revision = "0749_rebate_collective_correction"
down_revision = "0748_drop_invoices_register"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
