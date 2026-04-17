"""Phase 9 A4: contract_documents table

Revision ID: 0018
Revises: 0017
Create Date: 2026-04-17 14:30:00.000000

File attachments for contracts (signed PDF, annexes, NIP, OC policy, ZUS cert...).
Idempotent — 0001_initial's Base.metadata.create_all() may have already produced
this table on fresh CI DBs, so we guard every DDL statement.
"""

from alembic import op
import sqlalchemy as sa


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    doc_type = sa.Enum(
        "contract",
        "annex",
        "nda",
        "nip",
        "zus_certificate",
        "oc_policy",
        "other",
        name="contractdocumenttype",
    )
    doc_type.create(bind, checkfirst=True)

    op.execute("""
        CREATE TABLE IF NOT EXISTS contract_documents (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            file_path VARCHAR(512) NOT NULL,
            content_type VARCHAR(128),
            size_bytes INTEGER,
            doc_type contractdocumenttype NOT NULL DEFAULT 'other',
            expiry_date DATE,
            uploaded_by INTEGER REFERENCES users(id),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_documents_contract_id "
        "ON contract_documents(contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_documents_doc_type "
        "ON contract_documents(doc_type)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_documents CASCADE")
    sa.Enum(name="contractdocumenttype").drop(op.get_bind(), checkfirst=True)
