"""OAuth2 clients table for machine-to-machine API access.

Revision ID: 0086_oauth_clients
Revises: 0085_ai_features_settings
Create Date: 2026-05-08 13:00:00.000000

Creates ``oauth_clients`` to back the Settings → API integration panel
(Traffit gap #6 from docs/TRAFFIT_GAP_ROADMAP.md). External systems
(n8n, ChatGPT, Zapier, ...) authenticate via the OAuth2 client_credentials
grant — that token endpoint lands in a follow-up commit; this migration
just sets up storage.

Why:
- ``client_id`` UNIQUE → fast lookup at token issue.
- ``scopes`` as Postgres TEXT[] → trivial scope checks via ANY()
  without a separate join table; the scope vocabulary is small (≤20).
- ``last_used_at`` nullable → admin sees "never used" vs. "last used 2h ago"
  in the Settings UI.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0086_oauth_clients"
down_revision = "0085_ai_features_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "oauth_clients",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("client_id", sa.String(64), nullable=False, unique=True),
        sa.Column("secret_hash", sa.String(255), nullable=False),
        sa.Column(
            "scopes",
            postgresql.ARRAY(sa.String(64)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_oauth_clients_client_id", "oauth_clients", ["client_id"])


def downgrade() -> None:
    op.drop_index("ix_oauth_clients_client_id", table_name="oauth_clients")
    op.drop_table("oauth_clients")
