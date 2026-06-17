"""Traffit daily sync: watermark / run-state table.

Revision ID: 0136_traffit_sync_state
Revises: 0135_add_umowa_podpisana_stage
Create Date: 2026-06-17

Backs the scheduled Traffit → Nexus sync (app/tasks/traffit_sync.py). One row
per phase + ``__daily__`` / ``__full__`` scheduler markers. The persisted
watermark makes the background loop restart-safe (Coolify rebuilds on every
push and must not re-trigger imports).

Idempotent: CREATE TABLE IF NOT EXISTS so re-runs and DEBUG create_all coexist.
"""

from alembic import op

revision = "0136_traffit_sync_state"
down_revision = "0135_add_umowa_podpisana_stage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS traffit_sync_state (
            phase                varchar(50) PRIMARY KEY,
            last_synced_at       timestamptz,
            last_max_external_id bigint,
            last_run_started_at  timestamptz,
            last_run_finished_at timestamptz,
            last_status          varchar(20),
            stats                jsonb,
            created_at           timestamptz NOT NULL DEFAULT now(),
            updated_at           timestamptz NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS traffit_sync_state")
