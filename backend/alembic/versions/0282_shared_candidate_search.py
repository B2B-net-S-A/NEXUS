"""Shared criteria and durable exhaustive candidate search.

Revision ID: 0282_shared_candidate_search
Revises: 0281_candidate_skill_audit_index
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0282_shared_candidate_search"
down_revision = "0281_candidate_skill_audit_index"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("jobs", sa.Column("matching_requirements", postgresql.JSONB()))
    op.add_column(
        "jobs",
        sa.Column(
            "requirements_reviewed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "candidate_search_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column(
            "client_id", sa.Integer(), sa.ForeignKey("clients.id"), nullable=False
        ),
        sa.Column(
            "job_id", sa.Integer(), sa.ForeignKey("jobs.id", ondelete="SET NULL")
        ),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("request_context", postgresql.JSONB(), nullable=False),
        sa.Column("version_trace", postgresql.JSONB(), nullable=False),
        sa.Column("population_size", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(100)),
        sa.Column("metrics", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    for col in ("created_by", "state", "request_fingerprint"):
        op.create_index(
            f"ix_candidate_search_runs_{col}", "candidate_search_runs", [col]
        )
    op.create_table(
        "candidate_search_results",
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("candidate_search_runs.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("candidate_id", sa.Integer(), primary_key=True),
        sa.Column("candidate_version", sa.Text(), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("eligible", sa.Boolean()),
        sa.Column("fit_score", sa.Float()),
        sa.Column("measurement", sa.String(24)),
        sa.Column("evidence", postgresql.JSONB()),
        sa.Column("exclusion_reasons", postgresql.JSONB()),
    )
    op.create_index(
        "ix_candidate_search_results_page",
        "candidate_search_results",
        ["run_id", "eligible", "fit_score", "candidate_id"],
    )


def downgrade():
    op.drop_table("candidate_search_results")
    op.drop_table("candidate_search_runs")
    op.drop_column("jobs", "requirements_reviewed")
    op.drop_column("jobs", "matching_requirements")
