"""users.roles JSONB array for multi-role support.

Revision ID: 0110_users_multi_role
Revises: 0109_merge_three_heads
Create Date: 2026-05-18 12:30:00.000000

Adds ``users.roles`` (``JSONB`` array of role strings) so a user can hold
multiple roles simultaneously. ``users.role`` stays as the primary role for
legacy code paths (token issuance, single-role UI fallbacks); the new
``roles`` column is the authoritative source for permission checks.

Backfill seeds ``roles = [role::text]`` for every existing user so the
invariant ``users.role::text = ANY(users.roles)`` holds from day one.

Motivation: Marlena Rosół and Martyna Witkowska are Delivery Leads who
also work as TACs. Phase 7.2 AAD RBAC already places them in both
``NEXUS-DeliveryLeads`` and ``NEXUS-TACs`` groups; this migration makes
the application layer aware of the secondary role.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0110_users_multi_role"
down_revision = "0109_merge_three_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "roles",
            postgresql.JSONB,
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    # Backfill: each existing role becomes a single-element array.
    op.execute(
        "UPDATE users SET roles = jsonb_build_array(role::text) "
        "WHERE jsonb_array_length(roles) = 0"
    )


def downgrade() -> None:
    op.drop_column("users", "roles")
