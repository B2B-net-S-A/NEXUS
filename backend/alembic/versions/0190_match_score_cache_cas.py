"""CAS fence for the match-score cache (audyt P1-MATCH-02).

`candidate_job_match_scores` marks rows stale on candidate/job/profile edits so
the next read recomputes. But `_upsert_breakdown` cleared `stale=False`
unconditionally, so a score compute that STARTED before an invalidation could
overwrite it and resurrect a stale score (lost invalidation on a race).

This adds `invalidated_at TIMESTAMPTZ NULL`: `mark_stale_*` now stamps it with
the DB clock, and the write-back clears `stale` only when the row was not
invalidated after the compute began
(`invalidated_at IS NULL OR invalidated_at < compute_start`).

Nullable, no default → metadata-only, lock-light. Mirrored idempotently in
backend/entrypoint.sh (prod alembic is orphaned).

Revision ID: 0189_match_score_cache_cas
Revises: 0188_contract_alert_dedup
"""

from alembic import op

revision = "0190_match_score_cache_cas"
down_revision = "0189_application_submissions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_job_match_scores "
        "ADD COLUMN IF NOT EXISTS invalidated_at TIMESTAMPTZ NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_job_match_scores DROP COLUMN IF EXISTS invalidated_at"
    )
