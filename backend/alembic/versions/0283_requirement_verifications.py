"""Add reviewed requirement evidence, independent of extracted candidate data."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0283_requirement_verifications"
down_revision = "0282_shared_candidate_search"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "requirement_verifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "candidate_id",
            sa.Integer(),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "reviewer_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False
        ),
        sa.Column("group_key", sa.String(64), nullable=False),
        sa.Column("requirement", postgresql.JSONB(), nullable=False),
        sa.Column("requirements_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("usage_context", sa.Text(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('met', 'not_met', 'unknown')",
            name="ck_requirement_verification_status",
        ),
    )
    op.create_index(
        "ix_requirement_verification_lookup",
        "requirement_verifications",
        ["job_id", "candidate_id", "group_key", "id"],
    )


def downgrade():
    op.drop_table("requirement_verifications")
