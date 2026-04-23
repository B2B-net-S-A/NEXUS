"""Add `train_name` column to jobs for Phase 15 historical retrieval boost.

Revision ID: 0055_job_train_name
Revises: 0054_marketplace_notification_type
Create Date: 2026-04-23 22:00:00.000000

Context (Phase 15 / Phase D):
    `train_name` (np. "ART Payments" w Nordea, "TRAIN-X", "CIB Mortgages")
    is a free-text tag that groups roles belonging to the same programme or
    Agile Release Train at a client. It's the strongest historical-similarity
    signal after client_id because Nordea (and similar enterprise clients)
    publish cyclically near-identical roles for the same train.

    Historical-jobs retrieval uses `train_name` as a BOOST — not a hard
    filter — so roles without it still surface via semantic similarity.

Idempotent + reversible.
"""

from alembic import op
import sqlalchemy as sa


revision = "0055_job_train_name"
down_revision = "0054_marketplace_notification_type"
branch_labels = None
depends_on = None


INDEX_NAME = "ix_jobs_train_name_partial"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS train_name VARCHAR(128) NULL"
    )
    # Partial index — only non-null rows are queried, keeps index lean.
    op.execute(
        f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
        "ON jobs (client_id, train_name) "
        "WHERE train_name IS NOT NULL"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {INDEX_NAME}")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS train_name")
