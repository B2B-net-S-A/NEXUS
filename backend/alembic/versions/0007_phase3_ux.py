"""Phase 3: scorecard answers on candidate_stages + notifications types

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-16 13:30:00.000000

Adds candidate_stages.scorecard_answers (JSONB) so each move can store the
answers to the stage-specific scorecard defined in PipelineStageDef.scorecard_schema.

Idempotent.
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS scorecard_answers JSONB"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS scorecard_answers")
    )
