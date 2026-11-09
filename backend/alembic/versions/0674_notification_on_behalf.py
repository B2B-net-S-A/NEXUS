"""Powiadomienie u zastępcy pamięta, za kogo przyszło.

Revision ID: 0674_notification_on_behalf
Revises: 0673_own_hiring

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0674_notification_on_behalf"
down_revision = "0673_own_hiring"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE notifications ADD COLUMN IF NOT EXISTS on_behalf_of_user_id "
        "INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE notifications DROP COLUMN IF EXISTS on_behalf_of_user_id")
