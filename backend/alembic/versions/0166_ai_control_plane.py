"""Central AI gateway routing, compliance, budgets and immutable ledger.

Revision ID: 0166_ai_control_plane
Revises: 0165_ai_retrieval_foundation
"""

from alembic import op
import sqlalchemy as sa


revision = "0166_ai_control_plane"
down_revision = "0165_ai_retrieval_foundation"
branch_labels = None
depends_on = None

_NEW_FEATURES = (
    "embeddings",
    "reranking",
    "matching",
    "job_writer",
    "champion_profile",
    "match_explanation",
    "mindy",
    "uop_analysis",
    "criteria_suggestions",
    "cv_b2b",
)


def upgrade() -> None:
    # PostgreSQL enum values must be committed before they can be used by the
    # seed INSERTs in this migration.
    with op.get_context().autocommit_block():
        for feature in _NEW_FEATURES:
            op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{feature}'")

    op.add_column(
        "ai_features",
        sa.Column(
            "monthly_budget_usd",
            sa.Numeric(12, 4),
            nullable=False,
            server_default="0",
        ),
    )

    op.create_table(
        "ai_routing_state",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("registry_version", sa.String(64), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "activated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "ai_provider_compliance",
        sa.Column("provider", sa.String(32), primary_key=True),
        sa.Column(
            "production_allowed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "dpa_approved", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "zdr_approved", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "subprocessors_reviewed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("transfer_basis", sa.String(32), nullable=True),
        sa.Column(
            "approved_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "ai_routing_activation_log",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("previous_version", sa.String(64), nullable=False),
        sa.Column("registry_version", sa.String(64), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "activated_by",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_table(
        "ai_budget_reservations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column(
            "reserved_cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"
        ),
        sa.Column("actual_cost_usd", sa.Numeric(12, 6), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="reserved"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("request_id", name="uq_ai_budget_reservation_request"),
        sa.CheckConstraint(
            "status IN ('reserved', 'reconciled', 'failed')",
            name="ck_ai_budget_reservation_status",
        ),
    )
    op.create_index(
        "ix_ai_budget_reservations_request_id", "ai_budget_reservations", ["request_id"]
    )
    op.create_index(
        "ix_ai_budget_reservations_feature", "ai_budget_reservations", ["feature"]
    )
    op.create_index(
        "ix_ai_budget_reservations_period", "ai_budget_reservations", ["period_start"]
    )
    op.create_index(
        "ix_ai_budget_reservations_status", "ai_budget_reservations", ["status"]
    )

    op.create_table(
        "ai_call_ledger",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(64), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("subject_type", sa.String(32), nullable=True),
        sa.Column("subject_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(128), nullable=False),
        sa.Column("route_version", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("schema_version", sa.String(64), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cache_read_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "cache_write_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cost_usd", sa.Numeric(12, 6), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retried", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("pii", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("output_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    for name, columns in (
        ("ix_ai_call_ledger_request_id", ["request_id"]),
        ("ix_ai_call_ledger_feature", ["feature"]),
        ("ix_ai_call_ledger_user_id", ["user_id"]),
        ("ix_ai_call_ledger_client_id", ["client_id"]),
        ("ix_ai_call_ledger_provider", ["provider"]),
        ("ix_ai_call_ledger_status", ["status"]),
        ("ix_ai_call_ledger_created_at", ["created_at"]),
    ):
        op.create_index(name, "ai_call_ledger", columns)

    op.execute(
        "INSERT INTO ai_routing_state "
        "(id, registry_version, lock_version, reason) VALUES "
        "(1, 'v1_current', 1, 'Initial safe baseline')"
    )
    for feature in _NEW_FEATURES:
        op.execute(
            "INSERT INTO ai_features (feature, enabled, monthly_limit, monthly_budget_usd) "
            f"VALUES ('{feature}', true, 0, 0) ON CONFLICT (feature) DO NOTHING"
        )
    op.execute(
        "INSERT INTO ai_provider_compliance "
        "(provider, production_allowed, dpa_approved, zdr_approved, subprocessors_reviewed) VALUES "
        "('anthropic', true, false, false, false), "
        "('voyage', true, false, false, false), "
        "('openai', false, false, false, false)"
    )


def downgrade() -> None:
    op.drop_table("ai_call_ledger")
    op.drop_table("ai_budget_reservations")
    op.drop_table("ai_provider_compliance")
    op.drop_table("ai_routing_activation_log")
    op.drop_table("ai_routing_state")
    op.drop_column("ai_features", "monthly_budget_usd")
    # PostgreSQL enum values are intentionally retained; removing them safely
    # requires rebuilding the type and can break historic usage rows.
