"""Keep editor rendering assets with the approved version."""

from alembic import op
import sqlalchemy as sa

revision = "0296_cv_version_assets"
down_revision = "0295_cv_generated_draft"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cv_document_versions",
        sa.Column("template_content", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "cv_document_versions",
        sa.Column("consent_content", sa.LargeBinary(), nullable=True),
    )


def downgrade():
    op.drop_column("cv_document_versions", "consent_content")
    op.drop_column("cv_document_versions", "template_content")
