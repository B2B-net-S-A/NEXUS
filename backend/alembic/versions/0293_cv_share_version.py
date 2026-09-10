"""Pin generated links to an explicitly approved version; preserve old links."""

from alembic import op
import sqlalchemy as sa

revision = "0293_cv_share_version"
down_revision = "0292_cv_generated_docx"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cv_generated_share_tokens",
        sa.Column(
            "document_version_id",
            sa.Integer(),
            sa.ForeignKey("cv_document_versions.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("cv_generated_share_tokens", "document_version_id")
