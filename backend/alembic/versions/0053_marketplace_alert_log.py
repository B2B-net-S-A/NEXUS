"""Targ kandydatów: marketplace_alert_log (dedup table)

Revision ID: 0053_marketplace_alert_log
Revises: 0052_marketplace_pool_flag
Create Date: 2026-04-23 16:10:00.000000

Append-only log — dedup key dla notyfikacji z Targu kandydatów.
Jedna para (candidate_id, job_id) = jeden wpis na zawsze.
Drugi skan tego samego jobu nigdy nie wygeneruje kolejnej notyfikacji.
"""

from alembic import op


revision = "0053_marketplace_alert_log"
down_revision = "0052_marketplace_pool_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS marketplace_alert_log (
            id SERIAL PRIMARY KEY,
            candidate_id INTEGER NOT NULL
                REFERENCES candidates(id) ON DELETE CASCADE,
            job_id INTEGER NOT NULL
                REFERENCES jobs(id) ON DELETE CASCADE,
            score NUMERIC(5,2) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            notified_candidate_owner_id INTEGER
                REFERENCES users(id) ON DELETE SET NULL,
            notified_job_owner_id INTEGER
                REFERENCES users(id) ON DELETE SET NULL,
            CONSTRAINT uq_marketplace_alert_pair UNIQUE (candidate_id, job_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mal_candidate "
        "ON marketplace_alert_log (candidate_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mal_job "
        "ON marketplace_alert_log (job_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_mal_created "
        "ON marketplace_alert_log (created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS marketplace_alert_log")
