"""Invalidate the hybrid match-score cache after scoring recalibration.

Revision ID: 0143_invalidate_match_score_cache
Revises: 0142_contracts_framework_rate_line_manager
Create Date: 2026-06-23

The hybrid scoring engine was recalibrated (2026-06-23): the semantic layer now
applies a power-curve (``SEMANTIC_CALIBRATION_GAMMA``) and unknown salary/location
data is scored neutrally (``SCORE_UNKNOWN_NEUTRAL_FRACTION``) instead of 0. Every
``total_score`` persisted in ``candidate_job_match_scores`` therefore reflects the
OLD, deflated formula. Marking the rows ``stale=true`` forces the read-through
cache (``match_score_cache.get_cached_or_compute`` / ``bulk_get_or_compute``) to
recompute with the new engine on the next read — so kanban rings and
/recommendations stop serving the old deflated numbers.

Data-only migration (no schema change). Guarded with ``to_regclass`` so it is a
safe no-op on a fresh DB where the table has not been created yet, and chained
off the current ``0142`` head — the entrypoint runs ``alembic upgrade heads``,
so this lineage is applied.

Self-healing: staleness is recomputed lazily on read, so ``downgrade`` is a no-op.
"""

from alembic import op

revision = "0143_invalidate_match_score_cache"
down_revision = "0142_contracts_framework_rate_line_manager"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regclass('public.candidate_job_match_scores') IS NOT NULL THEN
                UPDATE candidate_job_match_scores
                   SET stale = true
                 WHERE stale = false;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    # No-op: cache staleness self-heals on the next read; nothing to revert.
    pass
