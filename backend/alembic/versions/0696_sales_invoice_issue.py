"""Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4): szkice, numeracja, wysyłka.

Revision ID: 0696_sales_invoice_issue
Revises: 0695_finance_ledger

Tabele ``client_invoice_series`` i ``client_issued_invoices`` oraz metoda
dopasowania ``issued`` w ``client_sales_invoices``. SQL i powody:
``app/services/client_invoice_issue_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).

Równolegle powstaje ``0695`` (koszty): przy scaleniu przepnij ``down_revision``
na tę migrację, która wejdzie pierwsza (``scripts/rechain_migration.py``).
"""

from alembic import op

from app.services import client_invoice_issue_schema as schema
from app.services import client_sales_invoices_schema as sales_schema

revision = "0696_sales_invoice_issue"
down_revision = "0695_finance_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)
    for stmt in sales_schema.METHOD_CONSTRAINT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
    # Metoda ``issued`` znika razem z wystawianiem: takie powiązania wracają do
    # ręcznych, żeby stary CHECK przyjął wiersze.
    op.execute(
        "UPDATE client_sales_invoices SET match_method = 'manual' "
        "WHERE match_method = 'issued'"
    )
    methods = ", ".join(f"'{m}'" for m in sales_schema.MATCH_METHODS if m != "issued")
    op.execute(
        "ALTER TABLE client_sales_invoices "
        "DROP CONSTRAINT IF EXISTS ck_client_sales_invoices_method"
    )
    op.execute(
        "ALTER TABLE client_sales_invoices ADD CONSTRAINT "
        "ck_client_sales_invoices_method CHECK "
        f"(match_method IS NULL OR match_method IN ({methods}))"
    )
