"""Płace K7b: pensje UoP, składniki miesiąca, oznaczenia L4, historia podstaw.

Revision ID: 0719_payroll_salaries
Revises: 0718_invoice_series_ebi24

Tabele ``payroll_salaries``, ``payroll_components``, ``payroll_absence_marks``
i ``payroll_basis_months`` oraz źródło pozycji listy ``salary``. DDL ma jedno
źródło (``app/services/hr_payroll_k7b_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``. Reguły:
``docs/claude/finanse-insights/ksiega-nexusa-k7b-place-uop.md``.
"""

from alembic import op

from app.services import hr_payroll_k7b_schema as schema

revision = "0719_payroll_salaries"
down_revision = "0718_invoice_series_ebi24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE payroll_list_lines DROP CONSTRAINT IF EXISTS ck_payroll_list_lines_source"
    )
    op.execute(
        "ALTER TABLE payroll_list_lines ADD CONSTRAINT ck_payroll_list_lines_source "
        "CHECK (source IN ('payroll_line', 'client_settlement', 'manual', 'missing')) NOT VALID"
    )
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
