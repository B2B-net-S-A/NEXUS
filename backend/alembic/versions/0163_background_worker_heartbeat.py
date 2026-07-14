"""Persist the singleton scheduler heartbeat and fencing token.

Revision ID: 0163_background_worker_heartbeat
Revises: 0162_user_token_version
Create Date: 2026-07-14 18:00:00.000000

The migration is additive and forward-only. Older application images ignore
the table, while a rollback of the new scheduler uses its default-off switch.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "0163_background_worker_heartbeat"
down_revision = "0162_user_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "background_worker_heartbeats",
        sa.Column("worker_name", sa.String(length=64), primary_key=True),
        sa.Column("instance_id", sa.String(length=64), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expected_tasks", sa.Integer(), nullable=False),
        sa.Column("running_tasks", sa.Integer(), nullable=False),
        sa.Column(
            "task_names",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.CheckConstraint(
            "fencing_token >= 1",
            name="ck_background_worker_fencing_token_positive",
        ),
        sa.CheckConstraint(
            "status IN ('starting', 'healthy', 'unhealthy')",
            name="ck_background_worker_heartbeat_status",
        ),
        sa.CheckConstraint(
            "expected_tasks >= 0",
            name="ck_background_worker_expected_tasks_nonnegative",
        ),
        sa.CheckConstraint(
            "running_tasks >= 0 AND running_tasks <= expected_tasks",
            name="ck_background_worker_running_tasks_range",
        ),
    )
    op.create_index(
        "ix_background_worker_heartbeats_heartbeat_at",
        "background_worker_heartbeats",
        ["heartbeat_at"],
    )


def downgrade() -> None:
    # Forward-only: previous app versions safely ignore the additive table.
    pass
