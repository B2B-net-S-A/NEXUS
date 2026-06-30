"""Invalidate the hybrid match-score cache after the 2026-06-30 calibration.

Revision ID: 0150_invalidate_match_cache_neutral065
Revises: 0149_contract_rates_scale3
Create Date: 2026-06-30

Follow-up to ``0143_invalidate_match_score_cache``. The hybrid scoring engine was
tuned again (2026-06-30, "AI scoring dalej zbyt surowy" on sparse Traffit jobs):

  * the ``location`` layer no longer hard-zeros when the job has no location or
    the candidate states no remote preference — it now awards the neutral
    ``SCORE_UNKNOWN_NEUTRAL_FRACTION`` like salary/availability/champion_fit, and
  * that fraction was raised 0.5 → 0.65 (one knob for all four no-signal
    metadata layers).

Every ``total_score`` persisted in ``candidate_job_match_scores`` therefore
reflects the OLD, deflated formula. Marking the rows ``stale=true`` forces the
read-through cache (``match_score_cache.bulk_get_or_compute`` /
``get_cached_or_compute``) to recompute with the new engine on the next read, so
kanban rings and /recommendations stop serving the old numbers.

Data-only migration (no schema change). Guarded with ``to_regclass`` so it is a
safe no-op on a fresh DB where the table does not exist yet, and chained off the
current ``0149`` head — the entrypoint runs ``alembic upgrade heads``, so this
lineage is applied. A single boolean UPDATE (no per-row compute), so it does not
risk the deploy smoke-test timeout that a heavy backfill migration would.

Self-healing: staleness is recomputed lazily on read, so ``downgrade`` is a no-op.
"""

from alembic import op

revision = "0150_invalidate_match_cache_neutral065"
down_revision = "0149_contract_rates_scale3"
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
