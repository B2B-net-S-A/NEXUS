"""Add rating + rating_comment columns to champion_profile_suggestions.

Revision ID: 0057_champion_suggestion_rating
Revises: 0056_pending_verification
Create Date: 2026-04-23 22:30:00.000000

Phase 15 / Phase C — lightweight feedback loop.

After a Delivery Lead applies or rejects a Champion Profile suggestion we
want to know whether the draft was useful. Minimal viable feedback:
  rating:         -1 (bezużyteczne) | 0 (nijak) | 1 (trafione)
  rating_comment: opcjonalna krótka notatka (np. "trzeba było mocno edytować")

Stored inline on the suggestion row — no new feedback table. Simplest shape
that unlocks offline eval: "accept-rate per source_type / client / prompt
version" + "rating distribution per source_type" w eval_champion_historical.

Idempotent + reversible.
"""

from alembic import op


revision = "0057_champion_suggestion_rating"
down_revision = "0056_pending_verification"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "ADD COLUMN IF NOT EXISTS rating SMALLINT NULL"
    )
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "ADD COLUMN IF NOT EXISTS rating_comment TEXT NULL"
    )
    # Guard rail: only -1/0/1 allowed. Drop if it exists so re-runs are safe.
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "DROP CONSTRAINT IF EXISTS chk_champion_suggestion_rating_range"
    )
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "ADD CONSTRAINT chk_champion_suggestion_rating_range "
        "CHECK (rating IS NULL OR rating IN (-1, 0, 1))"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "DROP CONSTRAINT IF EXISTS chk_champion_suggestion_rating_range"
    )
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "DROP COLUMN IF EXISTS rating_comment"
    )
    op.execute(
        "ALTER TABLE champion_profile_suggestions "
        "DROP COLUMN IF EXISTS rating"
    )
