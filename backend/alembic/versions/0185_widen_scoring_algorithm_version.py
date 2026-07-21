"""Widen candidate_job_match_scores.scoring_algorithm_version 32 → 64.

AI-P0-06 (migration-less code change, #857) folded the embedding model name
into ``SCORING_ALGORITHM_VERSION`` — e.g. ``score-v1-legacy+emb-voyage-3-large``
(34 chars). The column was ``VARCHAR(32)``, so every ``_upsert_breakdown``
INSERT failed with "value too long"; the write is wrapped in a best-effort
``try/except`` that rolls back, so it failed SILENTLY and the entire
match-score cache stopped persisting (each read recomputed, nothing cached).

Widen to 64. Mirrored in backend/entrypoint.sh (prod alembic is orphaned).

Revision ID: 0185_widen_scoring_algorithm_version
Revises: 0184_milestones_accepted_verification_only
"""

from alembic import op

revision = "0185_widen_scoring_algorithm_version"
down_revision = "0184_milestones_accepted_verification_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "ALTER COLUMN scoring_algorithm_version TYPE VARCHAR(64)"
    )


def downgrade() -> None:
    # Truncate would be lossy; the 32-char form is the buggy state we left, so
    # the downgrade just narrows the type back (existing long values would need
    # manual handling — deliberately not automated).
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "ALTER COLUMN scoring_algorithm_version TYPE VARCHAR(32)"
    )
