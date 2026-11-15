"""Serie faktur jak w eBI24: refaktury benefitów (BEN) i korekty UE (KORUE).

Revision ID: 0718_invoice_series_ebi24
Revises: 0717_autofill_detail_cleanup

Przebudowa CHECK-ów serii w ``client_invoice_series`` i ``client_issued_invoices``.
DDL ma jedno źródło (``app/services/client_invoice_series_ext_schema.py``);
entrypoint wykonuje je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_invoice_series_ext_schema as schema

revision = "0718_invoice_series_ebi24"
down_revision = "0717_autofill_detail_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
