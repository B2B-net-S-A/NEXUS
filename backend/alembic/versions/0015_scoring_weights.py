"""Phase D1: scoring_weight_profiles — tunable layer weights per scope

Revision ID: 0015
Revises: 0014
Create Date: 2026-04-17 13:00:00.000000

Lets admins store named weight profiles (semantic/skills/salary/location/availability)
and scope them globally, per-user, or per-client. When the scoring engine runs,
it picks the most specific active profile; missing profile → hardcoded defaults.

Schema
------
scoring_weight_profiles
  id                serial PK
  name              text, unique (informational — "Junior-friendly", etc.)
  user_id           FK users.id NULL  (per-user profile)
  client_id         FK clients.id NULL (per-client profile)
  weights           jsonb — {semantic:int, skills:int, salary:int, location:int, availability:int}
                          (values must sum to 100)
  active            bool default true
  created_at        timestamptz default now()
  updated_at        timestamptz default now()

Intentionally does NOT seed any row — the engine falls back to constants when empty.
"""

from alembic import op
import sqlalchemy as sa


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "scoring_weight_profiles",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column(
            "user_id",
            sa.Integer,
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer,
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("weights", sa.dialects.postgresql.JSONB, nullable=False),
        sa.Column("active", sa.Boolean, server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_scoring_weight_profiles_name"),
    )
    op.create_index(
        "ix_scoring_weight_profiles_user_id",
        "scoring_weight_profiles",
        ["user_id"],
    )
    op.create_index(
        "ix_scoring_weight_profiles_client_id",
        "scoring_weight_profiles",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_scoring_weight_profiles_client_id", table_name="scoring_weight_profiles"
    )
    op.drop_index(
        "ix_scoring_weight_profiles_user_id", table_name="scoring_weight_profiles"
    )
    op.drop_table("scoring_weight_profiles")
