"""Phase 7.2 — AAD group-based RBAC + auto-provisioning.

Revision ID: 0107_users_aad_groups
Revises: 0106_calendar_event_confirmation
Create Date: 2026-05-14 16:00:00.000000

Phase 7.2 of the M365 repair plan (.claude/plans/elegant-percolating-thimble.md).

Adds `users.aad_group_ids` (JSONB list of ``{"id": "<guid>", "displayName": "..."}``)
populated on every SSO login when ``AAD_GROUP_RBAC_ENABLED=true``. Role is then
derived from this list via ``AAD_GROUP_ROLE_MAP_JSON`` (first match wins).

GIN index on the JSONB column enables future "find all users in group X" admin
queries — required for offboarding audits (e.g. AAD group dissolution → list
affected NEXUS accounts) and Phase 7.4 group-scoped notifications.

Forward-only (no downgrade) — dropping the column would lose audit history of
which AAD groups a user belonged to at last login. If rollback is needed, set
``AAD_GROUP_RBAC_ENABLED=false`` and stop reading the column.
"""

from alembic import op


revision = "0107_users_aad_groups"
down_revision = "0106_calendar_event_confirmation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSONB so we can index with GIN and preserve `displayName` for audit/UI.
    # Default `[]` so existing users (legacy + new SSO before flag flip) read
    # as "no AAD groups known" without NULL handling churn.
    op.execute(
        "ALTER TABLE users "
        "ADD COLUMN IF NOT EXISTS aad_group_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
    )

    # GIN index supports `aad_group_ids @> '[{"id": "..."}]'::jsonb` queries —
    # the canonical way to ask "which users belong to AAD group X".
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_aad_group_ids "
        "ON users USING gin (aad_group_ids)"
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Forward-only: dropping users.aad_group_ids would lose RBAC audit state. "
        "To roll back behavior, set AAD_GROUP_RBAC_ENABLED=false."
    )
