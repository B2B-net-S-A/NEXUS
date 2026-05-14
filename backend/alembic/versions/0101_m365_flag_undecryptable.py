"""Flag M365 connections whose tokens cannot be decrypted (Phase 1 fire #1).

Revision ID: 0101_m365_flag_undecryptable
Revises: 0100_m365_reconnect_required
Create Date: 2026-05-14 09:05:00.000000

Step 2 of 2 — runs separately from 0100 because PostgreSQL/asyncpg refuses to
use a newly-added enum value inside the same transaction as the ALTER TYPE
(UnsafeNewEnumValueUsageError: "New enum values must be committed before they
can be used.").

Flips `is_active=false` / `last_sync_status='reconnect_required'` and wipes
the unusable ciphertext + delta cursors on every connection whose stored
``last_error`` matches the encryption-key-rotation failure pattern. The
frontend (Microsoft365Card.tsx) surfaces this as an amber banner with a CTA
to re-run OAuth.

Idempotent: WHERE matches only affected rows; re-running is a no-op.
"""

from alembic import op


revision = "0101_m365_flag_undecryptable"
down_revision = "0100_m365_reconnect_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
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
    # No-op — we don't want to restore broken state.
    pass
