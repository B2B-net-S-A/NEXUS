"""Durable AI operations, provider usage and generation leases.

Additive only: historical ai_usage_log remains untouched for reconciliation.
Revision ID: 0280_ai_metering_and_leases
Revises: 0279_hiring_manager_feedback
"""

from alembic import op
import sqlalchemy as sa

revision = "0280_ai_metering_and_leases"
down_revision = "0279_hiring_manager_feedback"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ai_operations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("actor_key", sa.String(48), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("units", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_ai_operations_feature", "ai_operations", ["feature"])
    op.create_index("ix_ai_operations_period_start", "ai_operations", ["period_start"])
    op.create_table(
        "ai_provider_calls",
        sa.Column("event_key", sa.String(200), primary_key=True),
        sa.Column(
            "operation_id",
            sa.String(36),
            sa.ForeignKey("ai_operations.id"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("request_id", sa.String(128)),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger()),
        sa.Column("output_tokens", sa.BigInteger()),
        sa.Column("cache_read_tokens", sa.BigInteger()),
        sa.Column("cache_creation_tokens", sa.BigInteger()),
        sa.Column("cache_creation_1h_tokens", sa.BigInteger()),
        sa.Column("estimated_cost_usd", sa.Numeric(18, 8)),
        sa.Column("price_version", sa.String(64)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_ai_provider_calls_operation_id", "ai_provider_calls", ["operation_id"]
    )
    op.create_index(
        "ix_ai_provider_calls_created_at", "ai_provider_calls", ["created_at"]
    )
    op.create_table(
        "ai_generation_leases",
        sa.Column("key", sa.String(128), primary_key=True),
        sa.Column("token", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "ai_spend_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(180), nullable=False, unique=True),
        sa.Column("message", sa.String(2000), nullable=False),
        sa.Column("recipient_id", sa.Integer()),
        sa.Column("in_app_at", sa.DateTime(timezone=True)),
        sa.Column("slack_sent_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.execute("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'ai_spend_alert'")


def downgrade():
    op.drop_table("ai_spend_alerts")
    op.drop_table("ai_generation_leases")
    op.drop_table("ai_provider_calls")
    op.drop_table("ai_operations")
