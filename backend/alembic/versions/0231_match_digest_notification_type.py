"""Match digest: wartość enuma notificationtype ``match_digest``.

Revision ID: 0231_match_digest_notification_type
Revises: 0230_notes_extraction_ai_feature
Create Date: 2026-08-18

Cotygodniowy push top dopasowań do rekruterów (app/tasks/match_digest.py).
ADD VALUE w autocommit (wymóg ALTER TYPE); zdublowane w safety-net
``entrypoint.sh`` (prod alembic bywa orphaned).
"""

from alembic import op

revision = "0231_match_digest_notification_type"
down_revision = "0230_notes_extraction_ai_feature"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'match_digest'")


def downgrade() -> None:
    # PostgreSQL nie kasuje wartości enuma in-place — zostaje (bezpieczne).
    pass
