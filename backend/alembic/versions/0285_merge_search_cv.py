"""Merge full-search and published CV-rule migration histories.

Both parent branches must be applied; this merge changes no schema or data.
"""

revision = "0285_merge_search_cv"
down_revision = (
    "0284_merge_search_signature",
    "0284_cv_highlight_policy",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
