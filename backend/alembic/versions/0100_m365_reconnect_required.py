"""Add 'reconnect_required' to m365syncstatus + flag affected connections.

Revision ID: 0100_m365_reconnect_required
Revises: 0099_cloudtalk_agent_mapping
Create Date: 2026-05-14 09:00:00.000000

Background: between 2026-05-07 and 2026-05-14 we burned 282 Sentry events on
`TokenCipherNotConfigured` because `M365_TOKEN_ENCRYPTION_KEY` rotated server-
side (likely during the CCX33 upgrade on 2026-05-07) and Coolify does not
version env vars, so the previous key is unrecoverable. Every M365 connection
has tokens encrypted under the dead key.

This migration:
1. Extends the m365syncstatus PG ENUM with `reconnect_required`.
2. Wipes ciphertext + delta cursors and flips `is_active=false` /
   `last_sync_status='reconnect_required'` on every connection whose stored
   error matches the decryption failure. The frontend (Microsoft365Card.tsx)
   surfaces this as an amber banner with a CTA to re-run OAuth.

Idempotent: re-running adds no extra rows; `IF NOT EXISTS` guards the enum
addition and the UPDATE matches only affected rows.
"""

from alembic import op


revision = "0100_m365_reconnect_required"
down_revision = "0099_cloudtalk_agent_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in older
    # PG versions, and Alembic wraps migrations in a transaction. We use the
    # transactional-safe ADD VALUE IF NOT EXISTS (PG 12+) and rely on the
    # AUTOCOMMIT-friendly form. Nexus runs PG 16-alpine — IF NOT EXISTS works.
    op.execute("ALTER TYPE m365syncstatus ADD VALUE IF NOT EXISTS 'reconnect_required'")

    # Flag every connection whose last error suggests a decryption failure.
    # Wipe ciphertext to stop the sync loop from re-trying every iteration.
    op.execute(
        """
        UPDATE m365_connections
        SET
            last_sync_status = 'reconnect_required',
            is_active = false,
            access_token_ct = '',
            refresh_token_ct = '',
            delta_token_messages = NULL,
            delta_token_events = NULL,
            last_error = COALESCE(last_error, 'Encryption key rotated 2026-05-07 — reconnect required.')
        WHERE
            last_error ILIKE '%TokenCipherNotConfigured%'
            OR last_error ILIKE '%key likely rotated%'
            OR last_error ILIKE '%key was rotated%'
        """
    )


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums. Downgrade would need to recreate
    # the type and reassign every column — not worth the risk for a flag.
    # Connections marked reconnect_required can stay; they're harmless.
    raise NotImplementedError(
        "Cannot downgrade: PostgreSQL has no ALTER TYPE DROP VALUE. "
        "Reconnect-required rows are harmless if the enum value stays."
    )
