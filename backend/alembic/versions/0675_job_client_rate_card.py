"""Rola z karty stawek klienta przy rekrutacji (raport miesięczny BNP).

Revision ID: 0675_job_client_rate_card
Revises: 0674_notification_on_behalf

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0675_job_client_rate_card"
down_revision = "0674_notification_on_behalf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS client_rate_card_id INTEGER NULL "
        "REFERENCES rate_cards (id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS client_rate_card_id")
