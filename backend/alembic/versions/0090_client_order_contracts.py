"""M:N link Order ↔ Candidate Contract (client_order_contracts).

Revision ID: 0090_client_order_contracts
Revises: 0089_client_orders
Create Date: 2026-05-08 16:15:00.000000
"""

from alembic import op


revision = "0090_client_order_contracts"
down_revision = "0089_client_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        "CREATE INDEX IF NOT EXISTS ix_coc_order "
        "ON client_order_contracts(order_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_coc_contract "
        "ON client_order_contracts(contract_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_coc_contract")
    op.execute("DROP INDEX IF EXISTS ix_coc_order")
    op.execute("DROP TABLE IF EXISTS client_order_contracts")
