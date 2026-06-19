"""Talent pools: pule osobiste (is_personal).

Revision ID: 0137_talent_pool_is_personal
Revises: 0136_traffit_sync_state
Create Date: 2026-06-19

Dodaje flagę ``is_personal`` na ``talent_pools``:
  * ``false`` — pula firmowa / wspólna (wszystkie istniejące pule).
  * ``true``  — pula indywidualna usera. Widoczna dla całego zespołu, ale
                zarządzana wyłącznie przez właściciela (``created_by``) / admina.

Indeks ``(is_personal, created_by)`` wspiera zakładkę „Pule osobiste" na
/talents (filtr is_personal=true + grupowanie po właścicielu).

Idempotent: ADD COLUMN / CREATE INDEX IF NOT EXISTS — współgra z DEBUG
``Base.metadata.create_all`` oraz z entrypoint safety-net (entrypoint.sh).
"""

from alembic import op

revision = "0137_talent_pool_is_personal"
down_revision = "0136_traffit_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE talent_pools "
        "ADD COLUMN IF NOT EXISTS is_personal BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_talent_pools_is_personal "
        "ON talent_pools (is_personal, created_by)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_talent_pools_is_personal")
    op.execute("ALTER TABLE talent_pools DROP COLUMN IF EXISTS is_personal")
