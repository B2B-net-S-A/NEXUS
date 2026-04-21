"""Phase 11 A1: client_one_pagers + client_contract_terms tables

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21 10:00:00.000000

Sales-material uploads (PDF/DOCX one-pagers) and structured MSA terms
(off-limits, internalization, payment, warranty) per client. Backs the
"Materiały" sub-tab on the client detail page.

Idempotent — guarded DDL matches 0018_contract_documents.py pattern.
"""

from alembic import op


revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS client_one_pagers (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            title VARCHAR(255) NOT NULL,
            description TEXT,
            version VARCHAR(50),
            filename VARCHAR(255) NOT NULL,
            file_path VARCHAR(512) NOT NULL,
            content_type VARCHAR(128),
            size_bytes INTEGER,
            uploaded_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_one_pagers_client_id "
        "ON client_one_pagers(client_id)"
    )

    op.execute("""
        CREATE TABLE IF NOT EXISTS client_contract_terms (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            off_limits_months INTEGER,
            off_limits_scope VARCHAR(500),
            off_limits_notes TEXT,
            internalization_fee_pct NUMERIC(5, 2),
            internalization_min_months INTEGER,
            internalization_notice_days INTEGER,
            internalization_notes TEXT,
            payment_net_days INTEGER,
            payment_currency VARCHAR(3),
            payment_invoice_cycle VARCHAR(50),
            payment_late_fees VARCHAR(500),
            payment_notes TEXT,
            notice_period_days INTEGER,
            warranty_replacement_days INTEGER,
            warranty_notes TEXT,
            other_clauses TEXT,
            updated_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_client_contract_terms_client UNIQUE (client_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_contract_terms CASCADE")
    op.execute("DROP TABLE IF EXISTS client_one_pagers CASCADE")
