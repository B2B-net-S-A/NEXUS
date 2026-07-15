"""Versioned match-score cache — add scoring_algorithm_version (plan PR4).

Revision ID: 0170_match_score_algorithm_version
Revises: 0169_match_telemetry
Create Date: 2026-07-15

The cache (candidate_job_match_scores) was keyed only by (candidate, job,
profile) + a stale flag, so a scoring formula change silently served stale
scores (AI-P0-06). This column lets the reader treat a row whose version !=
scoring_service.SCORING_ALGORITHM_VERSION as a miss. Existing rows backfill to
'score-v1-legacy' so nothing recomputes while AI_SCORING_CONTRACT_V2 is off.

Idempotent (ADD COLUMN IF NOT EXISTS) — mirrored in entrypoint.sh because prod
alembic is stuck multi-head.
"""

from alembic import op

revision = "0170_match_score_algorithm_version"
down_revision = "0169_match_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "ADD COLUMN IF NOT EXISTS scoring_algorithm_version VARCHAR(32) "
        "NOT NULL DEFAULT 'score-v1-legacy'"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "DROP COLUMN IF EXISTS scoring_algorithm_version"
    )
