"""Wyciszone kategorie powiadomień per użytkownik (22.09.2026).

Revision ID: 0349_notification_mutes
Revises: 0348_board_tasks

``users.muted_notification_categories`` = ``{kategoria: czas wyciszenia}``.
Kategorie i reguły: ``app/services/notification_categories.py``. Lustro
w ``entrypoint.sh`` (alembic na prodzie bywa osierocony) — ta sama instrukcja,
pilnuje ``test_notification_categories.py``.
"""

from alembic import op

revision = "0349_notification_mutes"
down_revision = "0348_board_tasks"
branch_labels = None
depends_on = None

ADD_MUTED_NOTIFICATION_CATEGORIES = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS muted_notification_categories "
    "JSONB NOT NULL DEFAULT '{}'::jsonb"
)


def upgrade() -> None:
    op.execute(ADD_MUTED_NOTIFICATION_CATEGORIES)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS muted_notification_categories")
