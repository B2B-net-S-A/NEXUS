"""Talent pool membership source_event + source_job_id

Revision ID: 0040_talent_pool_source_event
Revises: 0039_linkedin_metrics
Create Date: 2026-04-22 23:10:00.000000

Dodaje do `talent_pool_memberships` pola dla trackingu skąd kandydat
trafił do poola:
  - source_event (VARCHAR(50)) — np. 'cv_sent', 'manual', 'imported'
  - source_job_id (INTEGER FK jobs) — z którego JO przyszedł kandydat

Używane przez auto-add trigger po zmianie stage na cv_sent
(services/talent_pool_auto_add.py). Istniejące membershipy mają NULL
w obu polach — są traktowane jako 'manual'/'legacy'.
"""

from alembic import op


revision = "0040_talent_pool_source_event"
down_revision = "0039_linkedin_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE talent_pool_memberships
          ADD COLUMN IF NOT EXISTS source_event VARCHAR(50),
          ADD COLUMN IF NOT EXISTS source_job_id INTEGER
              REFERENCES jobs(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tpm_source_job_id "
        "ON talent_pool_memberships (source_job_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tpm_source_job_id")
    op.execute(
        """
        ALTER TABLE talent_pool_memberships
          DROP COLUMN IF EXISTS source_event,
          DROP COLUMN IF EXISTS source_job_id
        """
    )
