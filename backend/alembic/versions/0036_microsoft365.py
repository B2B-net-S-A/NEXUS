"""Microsoft 365 integration: connections, emails, attachments, calendar columns

Revision ID: 0036_microsoft365
Revises: 0034_merge_phase8_heads
Create Date: 2026-04-22 12:00:00.000000

Adds the schema backing Phase M365.1:

- `m365_connections` — one per user, holds encrypted OAuth2 tokens + delta cursors.
- `emails` — Graph messages cached locally, linked to candidates when matched.
- `email_attachments` — files referenced by an email, stored on disk.
- `calendar_events` extension: `m365_series_master_id`, `m365_change_key`
  (recurring series link + Graph etag for skip-unchanged).

Also creates enum types `m365syncstatus`, `emaildirection`, `emailmatchmethod`.

Idempotent + reversible. The calendar_events column adds are wrapped in
`DO $$` blocks following the `entrypoint.sh` safety-net pattern so partial
reruns from a crashed deploy don't double-apply.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0036_microsoft365"
down_revision = "0034_merge_phase8_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Enum types ────────────────────────────────────────────────────────
    # `create_type=False` on the columns below would skip implicit creation,
    # but we want explicit control + idempotency.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'm365syncstatus') THEN
                CREATE TYPE m365syncstatus AS ENUM ('idle', 'running', 'error');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'emaildirection') THEN
                CREATE TYPE emaildirection AS ENUM ('sent', 'received', 'draft');
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'emailmatchmethod') THEN
                CREATE TYPE emailmatchmethod AS ENUM (
                    'strict', 'smart_domain', 'smart_thread',
                    'smart_name', 'manual', 'unmatched'
                );
            END IF;
        END$$;
        """
    )

    # ── m365_connections ──────────────────────────────────────────────────
    op.create_table(
        "m365_connections",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            unique=True,
            nullable=False,
            index=True,
        ),
        sa.Column("tenant_id", sa.String(100), nullable=False),
        sa.Column("mailbox_upn", sa.String(255), nullable=False),
        sa.Column("access_token_ct", sa.Text, nullable=False),
        sa.Column("refresh_token_ct", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "scopes_granted",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("delta_token_messages", sa.Text, nullable=True),
        sa.Column("delta_token_events", sa.Text, nullable=True),
        sa.Column("synced_through", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "last_sync_status",
            postgresql.ENUM(
                "idle",
                "running",
                "error",
                name="m365syncstatus",
                create_type=False,
            ),
            server_default="idle",
            nullable=False,
        ),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("backfill_completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean,
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── emails ────────────────────────────────────────────────────────────
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("m365_message_id", sa.String(255), nullable=False, unique=True),
        sa.Column("m365_internet_message_id", sa.String(998), nullable=True),
        sa.Column("m365_conversation_id", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(998), nullable=True),
        sa.Column("from_address", sa.String(320), nullable=False),
        sa.Column("from_name", sa.String(255), nullable=True),
        sa.Column(
            "to_addresses",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "cc_addresses",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("body_html", sa.Text, nullable=True),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("body_preview", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "direction",
            postgresql.ENUM(
                "sent",
                "received",
                "draft",
                name="emaildirection",
                create_type=False,
            ),
            server_default="received",
            nullable=False,
        ),
        sa.Column(
            "has_attachments",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_read",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "is_private_filtered",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "match_method",
            postgresql.ENUM(
                "strict",
                "smart_domain",
                "smart_thread",
                "smart_name",
                "manual",
                "unmatched",
                name="emailmatchmethod",
                create_type=False,
            ),
            server_default="unmatched",
            nullable=False,
        ),
        sa.Column("match_confidence", sa.Float, nullable=True),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "matched_by_user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "raw_categories",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_emails_m365_message_id", "emails", ["m365_message_id"], unique=True
    )
    op.create_index(
        "ix_emails_m365_conversation_id", "emails", ["m365_conversation_id"]
    )
    op.create_index(
        "ix_emails_m365_internet_message_id", "emails", ["m365_internet_message_id"]
    )
    op.create_index("ix_emails_from_address", "emails", ["from_address"])
    op.create_index("ix_emails_received_at", "emails", ["received_at"])
    op.create_index(
        "ix_emails_candidate_received", "emails", ["candidate_id", "received_at"]
    )
    op.create_index(
        "ix_emails_user_conversation", "emails", ["user_id", "m365_conversation_id"]
    )
    op.create_index("ix_emails_user_received", "emails", ["user_id", "received_at"])

    # ── email_attachments ─────────────────────────────────────────────────
    op.create_table(
        "email_attachments",
        sa.Column("id", sa.Integer, primary_key=True, index=True),
        sa.Column(
            "email_id",
            sa.Integer,
            sa.ForeignKey("emails.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("m365_attachment_id", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column(
            "size_bytes",
            sa.Integer,
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "is_inline",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("storage_path", sa.String(1000), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True, index=True),
        sa.Column(
            "is_cv_candidate",
            sa.Boolean,
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("cv_parse_attempted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "parsed_candidate_id",
            sa.Integer,
            sa.ForeignKey("candidates.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("parse_error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # ── calendar_events: add M365-specific columns (idempotent) ────────────
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='calendar_events'
                  AND column_name='m365_series_master_id'
            ) THEN
                ALTER TABLE calendar_events
                    ADD COLUMN m365_series_master_id VARCHAR(255) NULL;
            END IF;
        END$$;
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calendar_events_m365_series "
        "ON calendar_events(m365_series_master_id)"
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='calendar_events'
                  AND column_name='m365_change_key'
            ) THEN
                ALTER TABLE calendar_events
                    ADD COLUMN m365_change_key VARCHAR(100) NULL;
            END IF;
        END$$;
        """
    )


def downgrade() -> None:
    # calendar_events extras (idempotent)
    op.execute("DROP INDEX IF EXISTS ix_calendar_events_m365_series")
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='calendar_events'
                  AND column_name='m365_change_key'
            ) THEN
                ALTER TABLE calendar_events DROP COLUMN m365_change_key;
            END IF;
            IF EXISTS (
                SELECT 1 FROM information_schema.columns
                WHERE table_name='calendar_events'
                  AND column_name='m365_series_master_id'
            ) THEN
                ALTER TABLE calendar_events DROP COLUMN m365_series_master_id;
            END IF;
        END$$;
        """
    )

    # Drop tables in FK-safe order.
    op.drop_table("email_attachments")

    for idx in (
        "ix_emails_user_received",
        "ix_emails_user_conversation",
        "ix_emails_candidate_received",
        "ix_emails_received_at",
        "ix_emails_from_address",
        "ix_emails_m365_internet_message_id",
        "ix_emails_m365_conversation_id",
        "ix_emails_m365_message_id",
    ):
        op.execute(f"DROP INDEX IF EXISTS {idx}")
    op.drop_table("emails")

    op.drop_table("m365_connections")

    # Drop enum types last (tables using them are gone).
    op.execute("DROP TYPE IF EXISTS emailmatchmethod")
    op.execute("DROP TYPE IF EXISTS emaildirection")
    op.execute("DROP TYPE IF EXISTS m365syncstatus")
