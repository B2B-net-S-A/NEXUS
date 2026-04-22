"""AI candidate proposal snapshots (Phase 13)

Revision ID: 0029
Revises: 0028
Create Date: 2026-04-21 12:00:00.000000

Immutable record of "what AI proposed when a job was created (or manually
regenerated)". Lets recruiters audit later: "these 20 candidates were the top
matches at creation time — who actually made it into pipeline?"

Table: proposal_snapshots
  id             serial PK
  job_id         FK → jobs.id ON DELETE CASCADE
  created_at     timestamptz default now() (index DESC with job_id)
  source         text enum: "create" | "manual_regenerate" | "job_updated"
  status         text enum: "pending" | "ready" | "failed"
  top_k          int default 20
  profile_id     int default 0 — mirrors CandidateJobMatchScore.profile_id
  candidate_ids  jsonb nullable — ordered list of candidate ids (null until ready)
  breakdowns     jsonb nullable — list of ScoreBreakdown.as_dict() (immutable snapshot)
  error_message  text nullable
  created_by     FK → users.id nullable (system-triggered can be NULL)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0029_proposal_snapshots"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "proposal_snapshots",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.Integer,
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Text,
            nullable=False,
            server_default=sa.text("'create'"),
        ),
        sa.Column(
            "status",
            sa.Text,
            nullable=False,
            server_default=sa.text("'pending'"),
        ),
        sa.Column(
            "top_k", sa.Integer, nullable=False, server_default=sa.text("20")
        ),
        sa.Column(
            "profile_id", sa.Integer, nullable=False, server_default=sa.text("0")
        ),
        sa.Column("candidate_ids", postgresql.JSONB, nullable=True),
        sa.Column("breakdowns", postgresql.JSONB, nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column(
            "created_by",
            sa.Integer,
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "source IN ('create', 'manual_regenerate', 'job_updated')",
            name="ck_proposal_snapshots_source",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'failed')",
            name="ck_proposal_snapshots_status",
        ),
    )
    # Fast "latest snapshot per job" lookup.
    op.create_index(
        "ix_proposal_snapshots_job_id_created_at",
        "proposal_snapshots",
        ["job_id", sa.text("created_at DESC")],
    )
    # Fast filtering by status (e.g. pending snapshots for cleanup jobs).
    op.create_index(
        "ix_proposal_snapshots_status",
        "proposal_snapshots",
        ["status"],
    )


def downgrade() -> None:
    op.drop_index("ix_proposal_snapshots_status", table_name="proposal_snapshots")
    op.drop_index(
        "ix_proposal_snapshots_job_id_created_at", table_name="proposal_snapshots"
    )
    op.drop_table("proposal_snapshots")
