"""Add 'reconnect_required' to m365syncstatus enum.

Revision ID: 0100_m365_reconnect_required
Revises: 0099_cloudtalk_agent_mapping
Create Date: 2026-05-14 09:00:00.000000

Step 1 of 2 — must run in its own migration before any UPDATE can reference
the new enum value. PostgreSQL/asyncpg raises UnsafeNewEnumValueUsageError if
a value added via ALTER TYPE is used in the same transaction:
   "New enum values must be committed before they can be used."

Step 2 (data wipe + reconnect-required flagging) is in 0101.

Background: between 2026-05-07 and 2026-05-14 we burned 282 Sentry events on
`TokenCipherNotConfigured` because `M365_TOKEN_ENCRYPTION_KEY` rotated server-
side (likely during the CCX33 upgrade on 2026-05-07) and Coolify does not
version env vars, so the previous key is unrecoverable. Every M365 connection
has tokens encrypted under the dead key.

Idempotent: ``ADD VALUE IF NOT EXISTS`` (PG 12+) — Nexus runs PG 16-alpine.
"""

from alembic import op


revision = "0100_m365_reconnect_required"
down_revision = "0099_cloudtalk_agent_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block; PG / asyncpg
    # raises UnsafeNewEnumValueUsageError if any later statement (even in a
    # subsequent migration in the same `upgrade head` invocation) uses it before
    # commit. autocommit_block commits the outer transaction, runs the DDL
    # outside any transaction, and opens a fresh one afterwards.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE m365syncstatus ADD VALUE IF NOT EXISTS 'reconnect_required'"
        )


def downgrade() -> None:
    # PostgreSQL has no DROP VALUE for enums. Connections marked
    # reconnect_required can stay; they're harmless if the value lives on.
    raise NotImplementedError(
        "Cannot downgrade: PostgreSQL has no ALTER TYPE DROP VALUE."
    )
