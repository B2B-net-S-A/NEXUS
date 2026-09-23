"""Kontrakty: cofnięcie zakończenia i powrót po przerwie.

Revision ID: 0359_contract_termination_reversal
Revises: 0357_contract_orders_card_dismissed

* ``contract_termination_snapshots`` — stan kontraktu i jego zamówień sprzed
  zakończenia współpracy; na nim stoi „Cofnij zakończenie".
* ``contracts.returned_from_contract_id`` — nowy kontrakt z „Powrotu po
  przerwie" wskazuje poprzedni.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0359_contract_termination_reversal"
down_revision = "0357_contract_orders_card_dismissed"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_termination_snapshots (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            effective_date DATE,
            status VARCHAR(16) NOT NULL DEFAULT 'open',
            source VARCHAR(16) NOT NULL DEFAULT 'termination',
            contract_before JSONB NOT NULL,
            orders JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            closed_at TIMESTAMPTZ,
            reversed_at TIMESTAMPTZ,
            reversed_by_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            reversal_payload JSONB,
            CONSTRAINT ck_contract_termination_snapshots_status
                CHECK (status IN ('open', 'reversed', 'superseded')),
            CONSTRAINT ck_contract_termination_snapshots_source
                CHECK (source IN ('termination', 'history')),
            CONSTRAINT ck_contract_termination_snapshots_reversed
                CHECK (status <> 'reversed' OR reversed_at IS NOT NULL)
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_contract_termination_snapshots_open "
        "ON contract_termination_snapshots (contract_id) WHERE status = 'open'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_termination_snapshots_contract "
        "ON contract_termination_snapshots (contract_id, id)"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS returned_from_contract_id "
        "INTEGER REFERENCES contracts(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_returned_from_contract_id "
        "ON contracts (returned_from_contract_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_contracts_returned_from_contract_id")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS returned_from_contract_id")
    op.execute("DROP TABLE IF EXISTS contract_termination_snapshots")
