"""Contract lifecycle invariant — new statuses + void metadata (P1-CONTRACT-01).

Backs the guarded contract state machine (``app.services.contract_lifecycle``):

* Two new ``contractstatus`` enum values:
    - ``ready_for_signature`` — a finalized-but-unsigned draft parks here instead
      of jumping to ``active``.
    - ``void`` — soft-delete / annul, used instead of a hard DELETE for executed
      contracts so documents + signature evidence are preserved.
* Two new ``contracts`` columns: ``voided_at`` / ``voided_by`` (set on void).

Enum ``ADD VALUE`` runs on Postgres 12+ inside the migration transaction (the new
values are not USED in the same transaction). Mirrored idempotently in
backend/entrypoint.sh (prod alembic is orphaned; every schema change must be
reflected there too), matching this DDL 1:1.

Revision ID: 0190_contract_lifecycle_invariant
Revises: 0189_application_submissions
"""

from alembic import op

revision = "0191_contract_lifecycle_invariant"
down_revision = "0190_match_score_cache_cas"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE contractstatus ADD VALUE IF NOT EXISTS 'ready_for_signature'"
    )
    op.execute("ALTER TYPE contractstatus ADD VALUE IF NOT EXISTS 'void'")
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS voided_at "
        "TIMESTAMP WITH TIME ZONE NULL"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS voided_by INTEGER NULL"
    )
    op.execute(
        "ALTER TABLE contracts DROP CONSTRAINT IF EXISTS fk_contracts_voided_by"
    )
    op.execute(
        "ALTER TABLE contracts ADD CONSTRAINT fk_contracts_voided_by "
        "FOREIGN KEY (voided_by) REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    # Postgres cannot DROP an enum VALUE, so the two statuses stay. Only the
    # columns are reversible.
    op.execute("ALTER TABLE contracts DROP CONSTRAINT IF EXISTS fk_contracts_voided_by")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS voided_by")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS voided_at")
