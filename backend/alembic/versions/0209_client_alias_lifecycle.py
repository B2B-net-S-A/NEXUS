"""Add reversible lifecycle provenance to imported client aliases.

Revision ID: 0209_client_alias_lifecycle
Revises: 0208_monthly_rate_retired
Create Date: 2026-07-30

Aliases created or revived by a portfolio import remain durable audit records.
Rollback archives them or restores their previous state instead of deleting
rows.  ``import_run_id`` identifies the run that most recently activated an
import-owned alias.
"""

from alembic import op


revision = "0209_client_alias_lifecycle"
down_revision = "0208_monthly_rate_retired"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE client_aliases
            ADD COLUMN IF NOT EXISTS import_run_id INTEGER NULL,
            ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_aliases
                ADD CONSTRAINT fk_client_aliases_import_run_id
                FOREIGN KEY (import_run_id) REFERENCES client_import_runs(id)
                ON DELETE SET NULL;
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_aliases_import_run_id "
        "ON client_aliases (import_run_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_aliases_archived_at "
        "ON client_aliases (archived_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_client_aliases_archived_at")
    op.execute("DROP INDEX IF EXISTS ix_client_aliases_import_run_id")
    op.execute(
        "ALTER TABLE client_aliases "
        "DROP CONSTRAINT IF EXISTS fk_client_aliases_import_run_id"
    )
    op.execute(
        """
        ALTER TABLE client_aliases
            DROP COLUMN IF EXISTS archived_at,
            DROP COLUMN IF EXISTS import_run_id
        """
    )
