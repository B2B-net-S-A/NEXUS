"""Indexes for full-search retention and candidate erasure.

`candidate_search_runs.completed_at` drives the 7-day retention selection.
`candidate_search_results.candidate_id` lets a candidate hard delete remove the
person's rows from every run without scanning the whole results table (its
primary key starts with `run_id`, so it cannot serve that lookup).

Revision ID: 0304_candidate_search_retention_indexes
Revises: 0303_inactive_client_cleanup
"""

from alembic import op

revision = "0304_candidate_search_retention_indexes"
down_revision = "0303_inactive_client_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The results table holds one row per candidate per run; build without
    # blocking the worker's writes.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_candidate_search_runs_completed_at "
            "ON candidate_search_runs (completed_at)"
        )
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
            "ix_candidate_search_results_candidate_id "
            "ON candidate_search_results (candidate_id)"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_candidate_search_results_candidate_id"
        )
        op.execute(
            "DROP INDEX CONCURRENTLY IF EXISTS ix_candidate_search_runs_completed_at"
        )
