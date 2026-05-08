"""Merge Traffit-feature branch with AI-modernization branch.

Revision ID: 0091_merge_traffit_features
Revises: 0090_pipeline_template_client_id, 0086_jobs_fts_index
Create Date: 2026-05-08 16:00:00.000000

Two parallel migration chains landed in the worktree:

- ``0085_ai_features_settings → 0086_oauth_clients → 0087-0090`` —
  Traffit gap features (#5, #6, #4, #3, #8, #7, #1).
- ``0085_embedding_cache → 0086_jobs_fts_index`` — AI modernization
  Items 3-8 merged onto main while this PR was in flight (#119, #120).

Alembic is a DAG, so multiple heads are tolerated, but
``alembic upgrade heads`` (plural) gets confused without a merge node
when production wants a single tip. This revision is empty — its sole
purpose is to declare both ancestors so ``upgrade head`` resolves.
"""

# Empty merge node — no schema change.

revision = "0091_merge_traffit_features"
down_revision = ("0090_pipeline_template_client_id", "0086_jobs_fts_index")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
