"""Persist standalone edits with revision checking and frozen rendering assets."""

from alembic import op
import sqlalchemy as sa

revision = "0295_cv_generated_draft"
down_revision = "0294_cv_version_owner"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cv_generated_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "generated_document_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("edit_revision", sa.Integer(), nullable=False),
        sa.Column("branded_version", sa.Integer(), nullable=False),
        sa.Column("branded_status", sa.String(20), nullable=False),
        sa.Column("branded_draft_html", sa.Text(), nullable=False),
        sa.Column("branded_template_content", sa.LargeBinary(), nullable=False),
        sa.Column("branded_consent_content", sa.LargeBinary(), nullable=True),
        sa.Column("branded_render_metadata", sa.JSON(), nullable=False),
        sa.Column("branded_language", sa.String(10), nullable=False),
        sa.Column("branded_template", sa.String(20), nullable=False),
        sa.Column("branded_docx_filename", sa.String(500), nullable=False),
    )


def downgrade():
    op.drop_table("cv_generated_drafts")
