"""Merge the independent AI and Analytics v1 migration branches.

Revision ID: 0170_merge_ai_analytics_heads
Revises: 0165_analytics_shadow_comparisons, 0169_ai_rollout
Create Date: 2026-07-15

Both parent migrations are additive. This revision intentionally performs no
schema mutation; it restores a single Alembic head for deterministic CI and
production startup ordering.
"""


revision = "0170_merge_ai_analytics_heads"
down_revision = (
    "0165_analytics_shadow_comparisons",
    "0169_ai_rollout",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    # Production analytics migrations remain additive during rollback window.
    pass
