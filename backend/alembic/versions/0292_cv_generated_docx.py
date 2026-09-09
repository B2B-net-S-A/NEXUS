"""Preserve exact newly generated CV artifacts; legacy rows remain unchanged."""

from alembic import op
import sqlalchemy as sa

revision = "0292_cv_generated_docx"
down_revision = "0291_cv_preview_docx"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cv_generated_documents",
        sa.Column("docx_content", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "cv_generated_documents", sa.Column("docx_sha256", sa.String(64), nullable=True)
    )


def downgrade():
    op.drop_column("cv_generated_documents", "docx_sha256")
    op.drop_column("cv_generated_documents", "docx_content")
