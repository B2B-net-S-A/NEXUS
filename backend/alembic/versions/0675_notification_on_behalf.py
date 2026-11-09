"""Powiadomienie u zastępcy pamięta, za kogo przyszło.

Revision ID: 0675_notification_on_behalf
Revises: 0674_job_client_rate_card

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0675_notification_on_behalf"
down_revision = "0674_job_client_rate_card"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS on_behalf_of_user_id "
        "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS on_behalf_of_user_id")
