"""merge 0036_microsoft365 + 0063_job_chat + 0032_client_materials into one head

Revision ID: 0064_merge_microsoft365_job_chat
Revises: 0036_microsoft365, 0063_job_chat, 0032_client_materials
Create Date: 2026-04-27 14:30:00.000000

Context:
    Prod-side alembic was failing with "Requested revision 0036_microsoft365
    overlaps with other requested revisions 0029" — backend entrypoint
    fell back to `Base.metadata.create_all()` which creates tables but
    SKIPS:
      - ALTER TYPE … ADD VALUE (enum extensions)
      - CREATE TRIGGER (FTS auto-update)
      - GIN/partial indexes (only some via metadata)

    Result: job_chat_messages table existed on prod but
    notificationtype/useractiontype enums lacked the new values, and
    POST /api/jobs/{id}/chat/messages returned 500.

    This migration merges the two divergent heads (0036_microsoft365
    leaf + 0063_job_chat) so alembic can run the chain end-to-end on
    next deploy. Because 0063_job_chat is fully idempotent (every DDL
    is wrapped in IF NOT EXISTS / CREATE OR REPLACE / DROP IF EXISTS +
    CREATE), re-applying it on top of a half-completed create_all is
    safe.

What this migration does:
    Nothing (no-op merge). Its only job is to rejoin the graph into
    a single head.
"""

from alembic import op


revision = "0064_merge_microsoft365_job_chat"
down_revision = ("0036_microsoft365", "0063_job_chat", "0032_client_materials")
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Backfill the `scheduled_rejection_emails.email_id` FK that 0045 had to
    # skip when it ran before 0036_microsoft365 created the `emails` table
    # (e.g. on a fresh CI database). Idempotent — does nothing on prod where
    # 0045 already added the constraint, and does nothing on re-run.
    op.execute(
        """
        DO $$
        BEGIN
            BEGIN
                ALTER TABLE scheduled_rejection_emails
                ADD CONSTRAINT fk_scheduled_rejection_emails_email_id
                FOREIGN KEY (email_id) REFERENCES emails(id) ON DELETE SET NULL;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END;
        END$$;
        """
    )


def downgrade() -> None:
    pass
