"""Durable edited-content review queue; no historical attempts synthesized."""

from alembic import op
import sqlalchemy as sa

revision = "0300_cv_approval_jobs"
down_revision = "0299_cv_preview_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cv_approval_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column(
            "generated_draft_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_drafts.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "candidate_stage_cv_id",
            sa.Integer(),
            sa.ForeignKey("candidate_stage_cvs.id", ondelete="CASCADE"),
        ),
        sa.Column(
            "generated_document_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column("expected_revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_content", sa.LargeBinary()),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
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
        sa.CheckConstraint(
            "(generated_draft_id IS NOT NULL) <> (candidate_stage_cv_id IS NOT NULL)",
            name="ck_cv_approval_job_owner",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'verified', 'rejected', 'failed', 'interrupted', 'cancelled')",
            name="ck_cv_approval_job_status",
        ),
        sa.CheckConstraint(
            "expected_revision >= 0", name="ck_cv_approval_job_revision"
        ),
        sa.UniqueConstraint(
            "user_id", "request_key", name="uq_cv_approval_job_request"
        ),
    )
    for column in (
        "generated_draft_id",
        "candidate_stage_cv_id",
        "status",
        "lease_expires_at",
    ):
        op.create_index(f"ix_cv_approval_jobs_{column}", "cv_approval_jobs", [column])


def downgrade():
    op.drop_table("cv_approval_jobs")
