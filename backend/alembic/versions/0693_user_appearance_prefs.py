"""Świat wyglądu NEXUSA zapisany na koncie, nie w przeglądarce.

Revision ID: 0693_user_appearance_prefs
Revises: 0692_client_einvoices

``users.appearance_prefs`` = ``{"world": "<id>", "world_before_season": "<id>"}``;
puste = bez świata. Reguła ``docs/claude/ui/swiaty-wygladu.md``.
Lustro w ``entrypoint.sh`` (pilnuje ``tests/test_appearance_prefs.py``).
"""

from alembic import op

revision = "0693_user_appearance_prefs"
down_revision = "0692_client_einvoices"
branch_labels = None
depends_on = None

DDL_STATEMENTS = (
    "ALTER TABLE users ADD COLUMN IF NOT EXISTS appearance_prefs JSONB NOT NULL DEFAULT '{}'::jsonb",
)


def upgrade() -> None:
    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS appearance_prefs")
