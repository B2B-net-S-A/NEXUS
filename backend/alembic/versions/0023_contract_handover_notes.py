"""Phase 9 C6: contract handover_notes column

Revision ID: 0023
Revises: 0022
Create Date: 2026-04-17 16:30:00.000000

Free-form internal notes per contract (visible only to staff).
"""

from alembic import op


revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contracts ADD COLUMN IF NOT EXISTS handover_notes TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS handover_notes")
