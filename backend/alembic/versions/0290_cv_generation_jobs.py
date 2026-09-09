"""Durable CV attempt ownership and private snapshot references."""

from alembic import op
import sqlalchemy as sa

revision = "0290_cv_generation_jobs"
down_revision = "0289_cv_approved_docx"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cv_generation_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "generated_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column(
            "second_generated_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column(
            "preview_id",
            sa.Integer(),
            sa.ForeignKey("client_cv_rule_previews.id", ondelete="CASCADE"),
            unique=True,
        ),
        sa.Column(
            "created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("input_storage_key", sa.String(500), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(64)),
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
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed', 'interrupted')",
            name="ck_cv_generation_job_status",
        ),
        sa.CheckConstraint(
            "kind IN ('new', 'upload', 'preview')", name="ck_cv_generation_job_kind"
        ),
    )
    op.create_index("ix_cv_generation_jobs_status", "cv_generation_jobs", ["status"])
    op.create_index(
        "ix_cv_generation_jobs_lease_expires_at",
        "cv_generation_jobs",
        ["lease_expires_at"],
    )


def downgrade():
    op.drop_table("cv_generation_jobs")
