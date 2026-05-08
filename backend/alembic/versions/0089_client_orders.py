"""Client orders (SOW/Zamówienia) pod konkretną MSA.

Revision ID: 0089_client_orders
Revises: 0088_client_contract_amendments
Create Date: 2026-05-08 16:10:00.000000
"""

from alembic import op


revision = "0089_client_orders"
down_revision = "0088_client_contract_amendments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'clientorderstatus') THEN
                CREATE TYPE clientorderstatus AS ENUM (
                    'draft', 'active', 'paused', 'completed', 'cancelled'
                );
            END IF;
        END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_orders (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            framework_contract_id INTEGER NOT NULL
                REFERENCES client_framework_contracts(id) ON DELETE RESTRICT,
            title VARCHAR(255) NOT NULL,
            description TEXT NULL,
            status clientorderstatus NOT NULL DEFAULT 'draft',
            start_date DATE NULL,
            end_date DATE NULL,
            total_value NUMERIC(12, 2) NULL,
            currency VARCHAR(3) NULL,
            positions_count INTEGER NULL,
            filename VARCHAR(255) NULL,
            file_path VARCHAR(512) NULL,
            content_type VARCHAR(128) NULL,
            size_bytes INTEGER NULL,
            created_by_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            notes TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_co_client ON client_orders(client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_co_framework "
        "ON client_orders(framework_contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_co_status ON client_orders(status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_co_end_date "
        "ON client_orders(end_date) WHERE end_date IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_co_end_date")
    op.execute("DROP INDEX IF EXISTS ix_co_status")
    op.execute("DROP INDEX IF EXISTS ix_co_framework")
    op.execute("DROP INDEX IF EXISTS ix_co_client")
    op.execute("DROP TABLE IF EXISTS client_orders")
    op.execute("DROP TYPE IF EXISTS clientorderstatus")
