"""Phase 12: Champion Card share tokens (send filled card to clients)

Revision ID: 0028
Revises: 0027
Create Date: 2026-04-18 09:00:00.000000

A recruiter can generate a time-limited token that reveals a read-only
ChampionCard view to an external reviewer (client). The public endpoint
validates the token and returns the card payload without any auth.

Table: champion_card_share_tokens
  token            TEXT primary key   — random 48-char URL-safe string
  candidate_stage_id FK → candidate_stages.id ON DELETE CASCADE
  created_by       FK → users.id
  created_at       timestamptz default now()
  expires_at       timestamptz nullable (NULL = never expires; default: +30d)
  revoked          boolean default false
"""

from alembic import op
import sqlalchemy as sa


revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "champion_card_share_tokens",
        sa.Column("token", sa.Text, primary_key=True),
        sa.Column(
            "candidate_stage_id",
            sa.Integer,
            sa.ForeignKey("candidate_stages.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "revoked", sa.Boolean, server_default=sa.text("false"), nullable=False
        ),
    )
    # Partial index for the "active, non-expired" lookup path.
    op.execute(
        "CREATE INDEX ix_champion_share_live "
        "ON champion_card_share_tokens (candidate_stage_id) "
        "WHERE revoked IS FALSE"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_champion_share_live")
    op.drop_table("champion_card_share_tokens")
