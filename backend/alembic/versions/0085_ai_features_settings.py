"""AI features: master toggle + per-feature config + monthly usage log.

Revision ID: 0085_ai_features_settings
Revises: 0084_saved_search_pinned_job
Create Date: 2026-05-08 12:00:00.000000

Introduces three tables backing the Settings → AI panel (Traffit-parity
feature #5 from the gap roadmap, see docs/TRAFFIT_GAP_ROADMAP.md):

- ``ai_master_toggle`` (singleton) — global kill-switch for all AI calls.
- ``ai_features`` — per-feature config: enabled flag + monthly call cap.
- ``ai_usage_log`` — aggregated monthly counts per (feature, user, period).

Default state seeded:
- master_toggle.enabled = TRUE (no surprise after deploy)
- ai_features rows for all 5 keys, enabled=TRUE, monthly_limit=0 (unlimited)

monthly_limit=0 is the explicit "no cap" sentinel — admins set non-zero
caps in the UI when cost control is needed. We seed unlimited so existing
AI flows keep working without admin intervention post-migration.
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0085_ai_features_settings"
down_revision = "0084_saved_search_pinned_job"
branch_labels = None
depends_on = None


_FEATURE_KEYS = (
    "scoring",
    "job_description_generator",
    "cv_parser",
    "candidate_summary",
    "champion_draft",
)


def upgrade() -> None:
    feature_enum = postgresql.ENUM(
        *_FEATURE_KEYS,
        name="aifeaturekey",
        create_type=False,
    )
    feature_enum.create(op.get_bind(), checkfirst=True)

    # ── ai_master_toggle (singleton row, id=1) ────────────────────────────────
    op.create_table(
        "ai_master_toggle",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.execute("INSERT INTO ai_master_toggle (id, enabled) VALUES (1, TRUE)")

    # ── ai_features (one row per AIFeatureKey) ────────────────────────────────
    op.create_table(
        "ai_features",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "feature",
            sa.Enum(*_FEATURE_KEYS, name="aifeaturekey", create_type=False),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "monthly_limit",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "updated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
    op.create_index("ix_ai_features_feature", "ai_features", ["feature"], unique=True)

    # Seed one row per feature key (enabled, unlimited).
    for key in _FEATURE_KEYS:
        op.execute(
            f"INSERT INTO ai_features (feature, enabled, monthly_limit) "
            f"VALUES ('{key}', TRUE, 0)"
        )

    # ── ai_usage_log (aggregated counts per feature × user × period) ──────────
    op.create_table(
        "ai_usage_log",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "feature",
            sa.Enum(*_FEATURE_KEYS, name="aifeaturekey", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_call_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "feature",
            "user_id",
            "period_start",
            name="uq_ai_usage_feature_user_period",
        ),
    )
    op.create_index("ix_ai_usage_log_feature", "ai_usage_log", ["feature"])
    op.create_index("ix_ai_usage_log_user_id", "ai_usage_log", ["user_id"])
    op.create_index("ix_ai_usage_log_period_start", "ai_usage_log", ["period_start"])


def downgrade() -> None:
    op.drop_index("ix_ai_usage_log_period_start", table_name="ai_usage_log")
    op.drop_index("ix_ai_usage_log_user_id", table_name="ai_usage_log")
    op.drop_index("ix_ai_usage_log_feature", table_name="ai_usage_log")
    op.drop_table("ai_usage_log")

    op.drop_index("ix_ai_features_feature", table_name="ai_features")
    op.drop_table("ai_features")

    op.drop_table("ai_master_toggle")

    sa.Enum(name="aifeaturekey").drop(op.get_bind(), checkfirst=True)
