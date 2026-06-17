"""Merge the two 0133 heads into a single tip.

Revision ID: 0134_merge_0133_heads
Revises: 0133_cv_generated_documents, 0133_signing_provider_refactor
Create Date: 2026-06-17

Two migrations both branched off ``0132_b2b_render_payload`` in parallel PRs:

- ``0133_cv_generated_documents``      — saved-CV list table (PR #507)
- ``0133_signing_provider_refactor``   — signing provider refactor (landed in parallel)

Production ``alembic_version`` ended up with both rows (multi-head). The
entrypoint runs ``upgrade heads`` (plural) so both already applied, but a single
tip is required before any further migration can chain cleanly. This node is
empty — its only job is to declare both ancestors (same pattern as
``0130_merge_0129_heads``).
"""

revision = "0134_merge_0133_heads"
down_revision = ("0133_cv_generated_documents", "0133_signing_provider_refactor")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
