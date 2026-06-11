"""Merge the two 0129 heads into a single tip.

Revision ID: 0130_merge_0129_heads
Revises: 0129_saved_search_alerts, 0129_note_briefing_fields
Create Date: 2026-06-11

Two migrations both branched off ``0128_b2b_number_unique``:

- ``0129_saved_search_alerts``  — saved-search alert columns + enum (PR #481)
- ``0129_note_briefing_fields`` — note briefing fields (landed in parallel)

Production ``alembic_version`` ended up with both rows (multi-head). The
entrypoint runs ``upgrade heads`` (plural) so deploys still apply, but a
single tip is required before any further migration can chain cleanly. This
node is empty — its only job is to declare both ancestors (same pattern as
``0091_merge_traffit_features``).
"""

revision = "0130_merge_0129_heads"
down_revision = ("0129_saved_search_alerts", "0129_note_briefing_fields")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
