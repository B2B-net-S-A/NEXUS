"""Approved CV versions and optimistic draft concurrency."""

from alembic import op
import sqlalchemy as sa

revision = "0285_cv_document_versions"
down_revision = "0284_cv_highlight_policy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "candidate_stage_cvs",
        sa.Column("edit_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "candidate_stage_cvs",
        sa.Column("branded_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "cv_document_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "candidate_stage_cv_id",
            sa.Integer(),
            sa.ForeignKey("candidate_stage_cvs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "generated_document_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="SET NULL"),
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_html", sa.Text(), nullable=False),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("template", sa.String(20)),
        sa.Column("language", sa.String(10)),
        sa.Column("candidate_first_name", sa.String(300)),
        sa.Column("job_title", sa.String(500)),
        sa.Column("snapshot_path", sa.String(512)),
        sa.Column("snapshot_filename", sa.String(500)),
        sa.Column("snapshot_size_bytes", sa.Integer()),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "approved_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.UniqueConstraint("candidate_stage_cv_id", "version"),
    )
    op.create_index(
        "ix_cv_document_versions_candidate_stage_cv_id",
        "cv_document_versions",
        ["candidate_stage_cv_id"],
    )
    op.add_column(
        "cv_share_tokens",
        sa.Column(
            "document_version_id",
            sa.Integer(),
            sa.ForeignKey("cv_document_versions.id", ondelete="CASCADE"),
        ),
    )


def downgrade():
    op.drop_column("cv_share_tokens", "document_version_id")
    op.drop_table("cv_document_versions")
    op.drop_column("candidate_stage_cvs", "branded_version")
    op.drop_column("candidate_stage_cvs", "edit_revision")
