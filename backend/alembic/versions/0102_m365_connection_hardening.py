"""M365 connection hardening: per-folder delta tokens, sync counters, send idempotency.

Revision ID: 0102_m365_connection_hardening
Revises: 0101_m365_flag_undecryptable
Create Date: 2026-05-14 10:00:00.000000

Phase 2 of the M365 repair plan (.claude/plans/elegant-percolating-thimble.md).

m365_connections:
- `delta_token_inbox` / `delta_token_sent` (TEXT) — Phase 2.5 split.
  The old `delta_token_messages` (single column) was shared by Inbox + SentItems
  syncs, so each folder overwrote the other's cursor and re-pulled the missing
  side as a "first time" backfill every iteration. The new columns keep one
  cursor per folder. Existing cursor copied into `delta_token_inbox` so the
  next sync continues smoothly (SentItems will do a one-time backfill).
  `delta_token_messages` is left in place but deprecated — drop in a later
  migration once we're sure no rolled-back code references it.
- `refresh_count` (INT, default 0) — Phase 2.2. Increment on every successful
  refresh_tokens() call. Used for anomaly detection (>10 refresh/hr = bug).
- `delta_reset_count` (INT, default 0) — Phase 2.4. Increment on each 410
  delta-invalidation. If >3 within `delta_last_reset_at`+24h, the sync loop
  flips the connection to `is_active=false` to stop a runaway full-refetch.
- `delta_last_reset_at` (TIMESTAMPTZ) — Phase 2.4. When the most recent 410
  reset happened. The 24h window is computed against this.

emails:
- `idempotency_key` (VARCHAR(128) UNIQUE NULLABLE) — Phase 2.6. Set by
  sender.send_new() to `sha256(user_id|sorted_recipients|subject|minute_bucket)`.
  Before each send the row is queried; a hit returns the cached row instead of
  issuing a duplicate Graph POST. Partial unique index — NULL means "this row
  was synced from Graph, not sent by us".

Idempotent — all `IF NOT EXISTS` guards.
"""

from alembic import op


revision = "0102_m365_connection_hardening"
down_revision = "0101_m365_flag_undecryptable"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Per-folder delta tokens.
    op.execute(
        "ALTER TABLE m365_connections "
        "ADD COLUMN IF NOT EXISTS delta_token_inbox TEXT NULL"
    )
    op.execute(
        "ALTER TABLE m365_connections "
        "ADD COLUMN IF NOT EXISTS delta_token_sent TEXT NULL"
    )
    # Migrate existing cursor into the inbox slot. Best guess — most active
    # folder is Inbox. SentItems will do a one-time short backfill on next run.
    op.execute(
        "UPDATE m365_connections "
        "SET delta_token_inbox = delta_token_messages "
        "WHERE delta_token_inbox IS NULL AND delta_token_messages IS NOT NULL"
    )

    # Sync counters for anomaly detection + recovery decisions.
    op.execute(
        "ALTER TABLE m365_connections "
        "ADD COLUMN IF NOT EXISTS refresh_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE m365_connections "
        "ADD COLUMN IF NOT EXISTS delta_reset_count INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE m365_connections "
        "ADD COLUMN IF NOT EXISTS delta_last_reset_at TIMESTAMP WITH TIME ZONE NULL"
    )

    # Send idempotency.
    op.execute(
        "ALTER TABLE emails "
        "ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(128) NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_emails_idempotency_key "
        "ON emails(idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )


def downgrade() -> None:
    # Forward-compat only — dropping columns mid-flight would lose cursors.
    raise NotImplementedError(
        "Cannot downgrade: dropping delta_token_inbox/sent would lose cursors. "
        "If you really need to roll back, manually copy delta_token_inbox into "
        "delta_token_messages first, then drop the new columns."
    )
