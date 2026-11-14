"""Płace liczone w NEXUSIE (K7a): dane osoby, parametry, listy płac.

Revision ID: 0704_payroll_lists
Revises: 0703_ledger_assets

Tabele ``payroll_person_data`` (dane kadrowo-płacowe, zaszyfrowane),
``payroll_parameter_versions`` (parametry od daty, zasiew 2026 do potwierdzenia
przez Płace), ``payroll_lists`` i ``payroll_list_lines`` (lista płac miesiąca
z wynikiem silnika brutto → netto), ``payroll_gross_inputs`` (kwoty wpisane
przez Płace) i ``payroll_year_openings`` (stan roku sprzed NEXUSA). DDL ma jedno
źródło (``app/services/hr_payroll_lists_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_payroll_lists_schema as schema

revision = "0704_payroll_lists"
down_revision = "0703_ledger_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
