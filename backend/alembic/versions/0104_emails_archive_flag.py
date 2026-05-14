"""Add emails.is_archived flag for Phase 5.1 bulk actions.

Revision ID: 0104_emails_archive_flag
Revises: 0103_email_fts
Create Date: 2026-05-14 12:30:00.000000

Phase 5.1 of the M365 plan (.claude/plans/elegant-percolating-thimble.md).

Adds a single boolean column `emails.is_archived` (NOT NULL DEFAULT false).
Archived emails are hidden from default thread previews so the bulk "Archive"
action visibly removes a message from the candidate sidebar.

Idempotent — `IF NOT EXISTS` guard.
"""

from alembic import op


revision = "0104_emails_archive_flag"
down_revision = "0103_email_fts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE emails "
        "ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT false"
    )
    # Partial index — most queries filter `is_archived = false`, so indexing
    # the small archived slice keeps writes cheap while letting the rare
    # "show archived" UI path stay fast.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_emails_user_archived "
        "ON emails(user_id) WHERE is_archived = true"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_emails_user_archived")
    op.execute("ALTER TABLE emails DROP COLUMN IF EXISTS is_archived")
