"""Client framework contracts (MSA) — PDF + status + okres obowiązywania.

Revision ID: 0087_client_framework_contracts
Revises: 0086_jobs_fts_index
Create Date: 2026-05-08 16:00:00.000000

Wprowadza tabelę ``client_framework_contracts`` — klient-poziomowe umowy
ramowe (MSA) z plikiem PDF, datami i statusem. Wersjonowanie przez
``parent_contract_id`` (self-FK).

Safety net (zgodnie z 0080 + project_kpi_coach_enum_gotcha memory):
- ``CREATE TYPE`` z ``DO $$ guard``
- ``CREATE TABLE IF NOT EXISTS``
- indeksy z ``IF NOT EXISTS``

Downgrade dropuje tabelę i typy enum (po dropie tabeli można usunąć typ).
"""

from alembic import op


revision = "0087_client_framework_contracts"
down_revision = "0086_jobs_fts_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Enums
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'frameworkcontractstatus') THEN
                CREATE TYPE frameworkcontractstatus AS ENUM (
                    'draft', 'pending_signature', 'active',
                    'expired', 'terminated', 'superseded'
                );
            END IF;
        END $$
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'frameworkcontractsignedvia') THEN
                CREATE TYPE frameworkcontractsignedvia AS ENUM ('upload', 'autenti');
            END IF;
        END $$
        """
    )

    # 2) Table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_framework_contracts (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            name VARCHAR(255) NOT NULL,
            status frameworkcontractstatus NOT NULL DEFAULT 'draft',
            effective_date DATE NULL,
            expiry_date DATE NULL,
            signed_via frameworkcontractsignedvia NOT NULL DEFAULT 'upload',
            currency VARCHAR(3) NULL,
            parent_contract_id INTEGER NULL
                REFERENCES client_framework_contracts(id) ON DELETE SET NULL,
            contract_terms_id INTEGER NULL
                REFERENCES client_contract_terms(id) ON DELETE SET NULL,
            filename VARCHAR(255) NULL,
            file_path VARCHAR(512) NULL,
            content_type VARCHAR(128) NULL,
            size_bytes INTEGER NULL,
            uploaded_by INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            uploaded_at TIMESTAMPTZ NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cfc_client "
        "ON client_framework_contracts(client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cfc_status "
        "ON client_framework_contracts(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cfc_expiry "
        "ON client_framework_contracts(expiry_date) "
        "WHERE expiry_date IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_cfc_parent "
        "ON client_framework_contracts(parent_contract_id) "
        "WHERE parent_contract_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_cfc_parent")
    op.execute("DROP INDEX IF EXISTS ix_cfc_expiry")
    op.execute("DROP INDEX IF EXISTS ix_cfc_status")
    op.execute("DROP INDEX IF EXISTS ix_cfc_client")
    op.execute("DROP TABLE IF EXISTS client_framework_contracts")
    op.execute("DROP TYPE IF EXISTS frameworkcontractsignedvia")
    op.execute("DROP TYPE IF EXISTS frameworkcontractstatus")
