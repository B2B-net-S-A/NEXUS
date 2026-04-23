"""Add jobs.tac_id — primary TAC (Talent Acquisition Consultant) of the job.

Revision ID: 0059_add_job_tac_id
Revises: 0058_editable_draft_contract
Create Date: 2026-04-24 12:00:00.000000

Context
-------
Projekty (Job) dotąd miały tylko `recruiter_id` i `delivery_lead_id`. Brakowało
jawnego pola "TAC klienta" — osoby, która jest przypisana do wszystkich
requestów danego klienta i prowadzi relację. Bez tego auto-assignment przy
tworzeniu projektu (POST /jobs) nie miał gdzie zapisać wyniku lookupu
`client → primary TAC`.

Adds:

  jobs.tac_id   — FK users(id) ON DELETE SET NULL, nullable, indexed

Idempotent + reversible. Kolumna nullable — brak potrzeby backfillu na
poziomie migracji; istniejące Joby zostają z NULL aż do uruchomienia
`scripts/backfill_job_owners.py`.
"""

from alembic import op


revision = "0059_add_job_tac_id"
down_revision = "0058_editable_draft_contract"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS tac_id INTEGER NULL"
    )
    # FK guard (drop+recreate so the migration is idempotent on rerun)
    op.execute(
        "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_tac_id"
    )
    op.execute(
        "ALTER TABLE jobs "
        "ADD CONSTRAINT fk_jobs_tac_id "
        "FOREIGN KEY (tac_id) REFERENCES users(id) "
        "ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_jobs_tac_id ON jobs (tac_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_tac_id")
    op.execute(
        "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS fk_jobs_tac_id"
    )
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS tac_id")
