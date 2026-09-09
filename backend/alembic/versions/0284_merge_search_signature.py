"""Merge shared-search and signature-permission migration histories.

Both parent branches must be applied; this merge changes no schema or data.
"""

revision = "0284_merge_search_signature"
down_revision = (
    "0283_requirement_verifications",
    "0282_b2b_signature_permission",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
