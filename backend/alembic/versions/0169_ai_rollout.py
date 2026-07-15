"""Add staged AI canary and rollback control plane.

Revision ID: 0169_ai_rollout
Revises: 0168_ai_evaluation
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0169_ai_rollout"
down_revision = "0168_ai_evaluation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_rollout_state",
        sa.Column("feature", sa.String(64), primary_key=True),
        sa.Column("baseline_registry", sa.String(64), nullable=False),
        sa.Column("target_registry", sa.String(64), nullable=False),
        sa.Column("stage", sa.String(16), nullable=False, server_default="shadow"),
        sa.Column("percentage", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("min_stage_hours", sa.Integer(), nullable=False, server_default="72"),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("offline_gate_reference", sa.String(256), nullable=False),
        sa.Column(
            "baseline_index_targets",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "target_index_targets",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("rollback_reason", sa.Text()),
        sa.Column(
            "started_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "stage_started_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("rollback_available_until", sa.DateTime(timezone=True)),
        sa.Column("monitoring_until", sa.DateTime(timezone=True)),
        sa.Column("next_regression_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "stage IN ('shadow','5','10','25','50','100')", name="ck_ai_rollout_stage"
        ),
        sa.CheckConstraint(
            "percentage IN (0,5,10,25,50,100)", name="ck_ai_rollout_percentage"
        ),
        sa.CheckConstraint(
            "status IN ('active','rolled_back','completed')",
            name="ck_ai_rollout_status",
        ),
        sa.CheckConstraint(
            "min_stage_hours BETWEEN 48 AND 72", name="ck_ai_rollout_min_hours"
        ),
    )
    op.create_table(
        "ai_rollout_observations",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("registry_version", sa.String(64), nullable=False),
        sa.Column("window_seconds", sa.Integer(), nullable=False),
        sa.Column("requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("provider_errors", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "privacy_incidents", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "critical_hallucinations", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "hallucination_samples", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("p95_increase_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column("cost_increase_pct", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "recall_at_20_drop_pp", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "ndcg_at_10_drop_pct", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column(
            "worst_slice_drop_pp", sa.Float(), nullable=False, server_default="0"
        ),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_ai_rollout_observations_feature", "ai_rollout_observations", ["feature"]
    )
    op.create_index(
        "ix_ai_rollout_observations_created_at",
        "ai_rollout_observations",
        ["created_at"],
    )
    op.create_table(
        "ai_rollout_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("event", sa.String(32), nullable=False),
        sa.Column("from_stage", sa.String(16)),
        sa.Column("to_stage", sa.String(16)),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "actor_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_ai_rollout_events_feature", "ai_rollout_events", ["feature"])
    op.create_table(
        "ai_rollout_reports",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("feature", sa.String(64), nullable=False),
        sa.Column("report_type", sa.String(20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("quality_passed", sa.Boolean(), nullable=False),
        sa.Column("artifact_ref", sa.String(512), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "report_type IN ('weekly','monthly_regression')",
            name="ck_ai_rollout_report_type",
        ),
    )
    op.create_index("ix_ai_rollout_reports_feature", "ai_rollout_reports", ["feature"])


def downgrade() -> None:
    op.drop_table("ai_rollout_reports")
    op.drop_table("ai_rollout_events")
    op.drop_table("ai_rollout_observations")
    op.drop_table("ai_rollout_state")
