"""Add 'historical_jobs' to champion_suggestion_source enum (Phase 15).

Revision ID: 0051_champion_historical_source
Revises: 0050_idx_candidate_stages_job_stage_moved
Create Date: 2026-04-23 21:00:00.000000

Phase 15 — Champion Profile: historical-jobs suggestion source.

Extends the existing `champion_suggestion_source` PG enum (created in
0031_champion_profile_suggestions) with a 5th value `historical_jobs`. When a
Delivery Lead opens a new role we now retrieve top-K semantically similar
CLOSED jobs (same-client preferred) that already have a populated
`champion_profile`, then feed them into an LLM to produce a delta-patch draft
the DL can review using the existing Phase 14 UI.

`ALTER TYPE ... ADD VALUE` cannot run inside a transaction in Postgres, so we
use `autocommit_block()` — same pattern as 0037_contracts_expansion.
"""

from alembic import op


revision = "0051_champion_historical_source"
down_revision = "0050_stage_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE champion_suggestion_source "
            "ADD VALUE IF NOT EXISTS 'historical_jobs'"
        )


def downgrade() -> None:
    # Postgres does not support removing a single enum value without rebuilding
    # the type and rewriting every dependent column. The add is idempotent and
    # harmless on rollback, so the downgrade is intentionally a no-op.
    pass
