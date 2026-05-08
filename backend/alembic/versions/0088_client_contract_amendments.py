"""Client contract amendments (aneksy do MSA).

Revision ID: 0088_client_contract_amendments
Revises: 0087_client_framework_contracts
Create Date: 2026-05-08 16:05:00.000000
"""

from alembic import op


revision = "0088_client_contract_amendments"
down_revision = "0087_client_framework_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_contract_amendments (
            id SERIAL PRIMARY KEY,
            framework_contract_id INTEGER NOT NULL
                REFERENCES client_framework_contracts(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            effective_date DATE NOT NULL,
            changes_summary TEXT NULL,
            old_terms JSONB NULL,
            new_terms JSONB NULL,
            filename VARCHAR(255) NULL,
            file_path VARCHAR(512) NULL,
            content_type VARCHAR(128) NULL,
            size_bytes INTEGER NULL,
            uploaded_by INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cca_framework "
        "ON client_contract_amendments(framework_contract_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cca_framework")
    op.execute("DROP TABLE IF EXISTS client_contract_amendments")
