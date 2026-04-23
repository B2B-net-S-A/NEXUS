"""Client ↔ TAC assignment matrix.

Revision ID: 0060_client_tac_assignments
Revises: 0059_add_job_tac_id
Create Date: 2026-04-24 12:15:00.000000

Context
-------
Model mentalny: **TAC to osoba przypisana do wszystkich requestów danego
klienta.** Klient może mieć w historii wielu TAC-ów (zmiany opiekunów), ale
tylko jeden jest "primary" w danym momencie. Analogia do `is_head` w
`delivery_lead_client_assignments` — ale z twardszą regułą:

  **Partial unique index** `uq_client_primary_tac` gwarantuje max 1 primary TAC
  per klient na poziomie bazy. `DeliveryLeadClientAssignment.is_head` tego nie
  ma (tylko logika aplikacyjna unset-przed-insert) — tu świadomie upgradujemy
  wzorzec, bo data-corruption w tym miejscu łamie auto-assign resolver.

Tabela:

  id               SERIAL PK
  tac_user_id      FK users(id) ON DELETE CASCADE
  client_id        FK clients(id) ON DELETE CASCADE
  is_primary       BOOLEAN NOT NULL DEFAULT FALSE
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()

Constraints:
  uq_client_tac           UNIQUE (tac_user_id, client_id)
  uq_client_primary_tac   UNIQUE (client_id) WHERE is_primary = TRUE
"""

from alembic import op


revision = "0060_client_tac_assignments"
down_revision = "0059_add_job_tac_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_tac_assignments (
            id SERIAL PRIMARY KEY,
            tac_user_id INTEGER NOT NULL
                REFERENCES users(id) ON DELETE CASCADE,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            is_primary BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_client_tac UNIQUE (tac_user_id, client_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_tac_assignments_client_id "
        "ON client_tac_assignments (client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_tac_assignments_tac_user_id "
        "ON client_tac_assignments (tac_user_id)"
    )
    # Partial unique index — max 1 primary TAC per client
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_primary_tac "
        "ON client_tac_assignments (client_id) WHERE is_primary = TRUE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_client_primary_tac")
    op.execute("DROP INDEX IF EXISTS ix_client_tac_assignments_tac_user_id")
    op.execute("DROP INDEX IF EXISTS ix_client_tac_assignments_client_id")
    op.execute("DROP TABLE IF EXISTS client_tac_assignments")
