"""Merge the two 0138 heads into a single tip.

Revision ID: 0139_merge_0138_heads
Revises: 0138_candidate_expected_hourly_rate, 0138_contracts_per_client_register
Create Date: 2026-06-22

Two migrations both branched off ``0137_talent_pool_is_personal`` in parallel PRs:

- ``0138_candidate_expected_hourly_rate``   — candidates hourly-rate filter (PR #554)
- ``0138_contracts_per_client_register``    — per-client contract register (PR #551)

Production ``alembic_version`` ends up with both rows (multi-head). The
entrypoint runs ``upgrade heads`` (plural) so both already applied, but a single
tip is required before any further migration can chain cleanly. This node is
empty — its only job is to declare both ancestors (same pattern as
``0134_merge_0133_heads`` / ``0130_merge_0129_heads``).
"""

revision = "0139_merge_0138_heads"
down_revision = (
    "0138_candidate_expected_hourly_rate",
    "0138_contracts_per_client_register",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
