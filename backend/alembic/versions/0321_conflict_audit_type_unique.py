"""candidate_conflicts: audyt dezaktywacji + unikalność per typ + indeks wygaśnięć.

Revision ID: 0321_conflict_audit_type_unique
Revises: 0320_contract_candidate_contact

* ``deactivated_at`` / ``deactivated_by`` / ``deactivation_reason`` — do tej
  rewizji dezaktywacja zdejmowała konflikt bez śladu, kto i dlaczego.
* ``uq_candidate_conflict_active`` (kandydat, klient) → ``..._active_type``
  (kandydat, klient, typ): NDA u klienta nie może blokować zapisu blacklisty
  u tego samego klienta. Poszerzenie klucza nie wymaga migracji danych — stary
  indeks gwarantował brak duplikatów.
* ``ix_candidate_conflicts_active_expires`` — alert DL „konflikt wygasł"
  i filtr rejestru „wygasa w N dni".

Lustro DDL: ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``tests/test_entrypoint_candidate_conflicts_mirror.py``.
"""

from alembic import op

revision = "0321_conflict_audit_type_unique"
down_revision = "0320_contract_candidate_contact"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_conflicts "
        "ADD COLUMN IF NOT EXISTS deactivated_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE candidate_conflicts ADD COLUMN IF NOT EXISTS deactivated_by "
        "INTEGER REFERENCES users(id) ON DELETE SET NULL"
    )
    op.execute(
        "ALTER TABLE candidate_conflicts "
        "ADD COLUMN IF NOT EXISTS deactivation_reason TEXT"
    )
    op.execute("DROP INDEX IF EXISTS uq_candidate_conflict_active")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_conflict_active_type "
        "ON candidate_conflicts (candidate_id, client_id, type) "
        "WHERE active = true"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_candidate_conflicts_active_expires "
        "ON candidate_conflicts (expires_at) "
        "WHERE active = true AND expires_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_candidate_conflicts_active_expires")
    op.execute("DROP INDEX IF EXISTS uq_candidate_conflict_active_type")
    # Stary klucz nie zna typu: zostaw aktywny wyłącznie najnowszy wiersz pary
    # (kandydat, klient), resztę dezaktywuj — inaczej CREATE UNIQUE INDEX padnie.
    op.execute(
        """
        UPDATE candidate_conflicts cc
        SET active = false
        FROM (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY candidate_id, client_id
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM candidate_conflicts
            WHERE active = true
        ) ranked
        WHERE cc.id = ranked.id AND ranked.rn > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_candidate_conflict_active "
        "ON candidate_conflicts (candidate_id, client_id) WHERE active = true"
    )
    op.execute(
        "ALTER TABLE candidate_conflicts DROP COLUMN IF EXISTS deactivation_reason"
    )
    op.execute("ALTER TABLE candidate_conflicts DROP COLUMN IF EXISTS deactivated_by")
    op.execute("ALTER TABLE candidate_conflicts DROP COLUMN IF EXISTS deactivated_at")
