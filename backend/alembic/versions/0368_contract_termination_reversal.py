"""Kontrakty: cofnięcie zakończenia i powrót po przerwie.

Revision ID: 0368_contract_termination_reversal
Revises: 0367_contract_agreement_termination

* ``contract_termination_snapshots`` — stan kontraktu i jego zamówień sprzed
  zakończenia współpracy; na nim stoi „Cofnij zakończenie".
* ``contracts.returned_from_contract_id`` — nowy kontrakt z „Powrotu po
  przerwie" wskazuje poprzedni.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0368_contract_termination_reversal"
down_revision = "0367_contract_agreement_termination"
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


# Runda 10 (R10-N12-4): migawki stanu sprzed zakończenia są jedynym źródłem
# „Cofnij zakończenie”, a `returned_from_contract_id` — śladem „Powrotu po
# przerwie”. Downgrade kasował je bez ostrzeżenia.
REFUSE_WITH_TERMINATION_SNAPSHOTS = """DO $$
DECLARE
    has_rows boolean := false;
BEGIN
    IF to_regclass('contract_termination_snapshots') IS NOT NULL THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM contract_termination_snapshots)'
            INTO has_rows;
    END IF;
    IF NOT has_rows AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'contracts'
          AND column_name = 'returned_from_contract_id'
    ) THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM contracts'
            || ' WHERE returned_from_contract_id IS NOT NULL)' INTO has_rows;
    END IF;
    IF has_rows THEN
        RAISE EXCEPTION 'Downgrade 0368 odmawia: są migawki zakończeń albo powroty po przerwie — bez nich „Cofnij zakończenie” przestanie działać. Zostaw tę rewizję albo przenieś dane ręcznie.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_TERMINATION_SNAPSHOTS)
    op.execute("DROP INDEX IF EXISTS ix_contracts_returned_from_contract_id")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS returned_from_contract_id")
    op.execute("DROP TABLE IF EXISTS contract_termination_snapshots")
