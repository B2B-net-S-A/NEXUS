"""Merge full-search and MD-budget migration histories.

Both parent branches must be applied; this merge changes no schema or data.
"""

revision = "0286_merge_search_orders"
down_revision = (
    "0285_merge_search_cv",
    "0285_md_budget_mode",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
