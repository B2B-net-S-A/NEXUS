"""Durable indexing outbox — match_index_outbox (plan PR5).

Revision ID: 0171_index_outbox
Revises: 0170_match_score_algorithm_version
Create Date: 2026-07-15

Idempotent (CREATE TABLE/INDEX IF NOT EXISTS) and mirrored in entrypoint.sh
(prod alembic multi-head). Consumed by the flag-gated index_outbox worker.
"""

from alembic import op

revision = "0171_index_outbox"
down_revision = "0170_match_score_algorithm_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS match_index_outbox (
            id BIGSERIAL PRIMARY KEY,
            entity_type VARCHAR(16) NOT NULL,
            entity_id INTEGER NOT NULL,
            entity_revision BIGINT NOT NULL,
            desired_hash VARCHAR(64) NOT NULL,
            operation VARCHAR(16) NOT NULL DEFAULT 'upsert',
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error VARCHAR(500),
            indexed_hash VARCHAR(64),
            indexed_revision BIGINT,
            heartbeat_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_pending "
        "ON match_index_outbox (status, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_entity "
        "ON match_index_outbox (entity_type, entity_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_match_index_outbox_status "
        "ON match_index_outbox (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS match_index_outbox")
