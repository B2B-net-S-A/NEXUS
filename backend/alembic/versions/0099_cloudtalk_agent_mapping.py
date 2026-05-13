"""CloudTalk agent ↔ user mapping + extended call fields.

Revision ID: 0099_cloudtalk_agent_mapping
Revises: 0098_merge_heads
Create Date: 2026-05-13 13:00:00.000000

- users.cloudtalk_agent_id INTEGER UNIQUE NULLABLE — set once per user by
  POST /api/cloudtalk/agents/{id}/assign. UNIQUE because CloudTalk agent
  is a 1:1 physical phone/seat — same agent can't be two users.
- calls.cloudtalk_agent_id INTEGER NULLABLE — denormalized so historical
  Call rows survive even if the User → CloudTalk mapping changes later.
- calls.started_at TIMESTAMP WITH TIME ZONE NULLABLE — CloudTalk delivers
  the exact start time per webhook event; nicer than relying on the row's
  ``created_at``.

All changes guarded with ``IF NOT EXISTS`` so this migration is safe to
re-apply on any prod that may have drifted (see memory
``project_alembic_drift.md``).
"""

from alembic import op


revision = "0099_cloudtalk_agent_mapping"
down_revision = "0098_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # users.cloudtalk_agent_id
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS cloudtalk_agent_id INTEGER NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_users_cloudtalk_agent_id "
        "ON users(cloudtalk_agent_id) "
        "WHERE cloudtalk_agent_id IS NOT NULL"
    )

    # calls.cloudtalk_agent_id
    op.execute(
        "ALTER TABLE calls "
        "ADD COLUMN IF NOT EXISTS cloudtalk_agent_id INTEGER NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calls_cloudtalk_agent_id "
        "ON calls(cloudtalk_agent_id) "
        "WHERE cloudtalk_agent_id IS NOT NULL"
    )

    # calls.started_at — exact CloudTalk-side start time
    op.execute(
        "ALTER TABLE calls "
        "ADD COLUMN IF NOT EXISTS started_at TIMESTAMP WITH TIME ZONE NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_calls_started_at "
        "ON calls(started_at DESC NULLS LAST)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_calls_started_at")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS started_at")
    op.execute("DROP INDEX IF EXISTS ix_calls_cloudtalk_agent_id")
    op.execute("ALTER TABLE calls DROP COLUMN IF EXISTS cloudtalk_agent_id")
    op.execute("DROP INDEX IF EXISTS uq_users_cloudtalk_agent_id")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS cloudtalk_agent_id")
