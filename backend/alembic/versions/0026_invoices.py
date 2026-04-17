"""Phase 9 C1: invoices table

Revision ID: 0026
Revises: 0025
Create Date: 2026-04-17 18:00:00.000000

Lightweight invoice tracking (no generation — staff enters invoice metadata
after issuing it elsewhere). Used for DSO (Days Sales Outstanding) reporting.
"""

from alembic import op
import sqlalchemy as sa


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    direction = sa.Enum("to_client", "from_contractor", name="invoicedirection")
    direction.create(bind, checkfirst=True)
    inv_status = sa.Enum(
        "issued", "sent", "paid", "overdue", "cancelled", name="invoicestatus"
    )
    inv_status.create(bind, checkfirst=True)

    op.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            direction invoicedirection NOT NULL,
            invoice_number VARCHAR(64) NOT NULL,
            period_month INTEGER,
            period_year INTEGER,
            issue_date DATE NOT NULL,
            due_date DATE,
            paid_date DATE,
            amount INTEGER NOT NULL,
            currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
            status invoicestatus NOT NULL DEFAULT 'issued',
            pdf_document_id INTEGER REFERENCES contract_documents(id) ON DELETE SET NULL,
            notes TEXT,
            created_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_invoices_contract_id ON invoices(contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_invoices_status ON invoices(status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS invoices CASCADE")
    sa.Enum(name="invoicestatus").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="invoicedirection").drop(op.get_bind(), checkfirst=True)
