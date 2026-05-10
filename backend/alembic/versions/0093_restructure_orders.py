"""Restructure client_orders: M:N → N:1 with Contract + add job_id.

Revision ID: 0093_restructure_orders
Revises: 0092_notification_types_framework
Create Date: 2026-05-11 09:00:00.000000

Refactor model do rzeczywistości body-leasingu:

- Order ZAWSZE pod konkretnym kandydackim Contract (1:N, NOT M:N)
- Order pochodzi z konkretnej rekrutacji (Job)
- Order może być bez MSA (framework_contract_id nullable)
- 1 Order = 1 osoba (positions_count usunięte)

Bezpieczeństwo: 0 rekordów w client_orders i client_order_contracts (zweryfikowane
przez postgres-nexus MCP przed migracją), więc DROP COLUMN + ADD COLUMN NOT NULL
nie wymaga backfillu.
"""

from alembic import op


revision = "0093_restructure_orders"
down_revision = "0092_notification_types_framework"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Drop M:N table (0 rekordów)
    op.execute("DROP INDEX IF EXISTS ix_coc_contract")
    op.execute("DROP INDEX IF EXISTS ix_coc_order")
    op.execute("DROP TABLE IF EXISTS client_order_contracts")

    # 2) Restructure client_orders
    # framework_contract_id → nullable (Order może istnieć bez MSA)
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN framework_contract_id DROP NOT NULL"
    )

    # Drop positions_count (1 Order = 1 osoba)
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS positions_count")

    # Add contract_id (FK do kandydackiego Contract, NOT NULL)
    # NOT NULL safe bo 0 rekordów w client_orders
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS contract_id INTEGER "
        "REFERENCES contracts(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN contract_id SET NOT NULL"
    )

    # Add job_id (FK do Job rekrutacji, nullable)
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS job_id INTEGER "
        "REFERENCES jobs(id) ON DELETE SET NULL"
    )

    # Indexes
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_co_contract ON client_orders(contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_co_job ON client_orders(job_id) "
        "WHERE job_id IS NOT NULL"
    )


def downgrade() -> None:
    # Restore positions_count (default 1)
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS positions_count INTEGER"
    )
    op.execute("DROP INDEX IF EXISTS ix_co_job")
    op.execute("DROP INDEX IF EXISTS ix_co_contract")
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS job_id")
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS contract_id")
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN framework_contract_id SET NOT NULL"
    )

    # Recreate M:N table (empty)
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_order_contracts (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL
                REFERENCES client_orders(id) ON DELETE CASCADE,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            assigned_by_user_id INTEGER NULL
                REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT uq_order_contract UNIQUE (order_id, contract_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coc_order ON client_order_contracts(order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coc_contract "
        "ON client_order_contracts(contract_id)"
    )
