"""Keep the original generation template; legacy rows remain explicitly empty."""

from alembic import op
import sqlalchemy as sa

revision = "0298_cv_generation_template"
down_revision = "0297_cv_request_receipts"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cv_generated_documents",
        sa.Column("consent_content", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "cv_generated_documents",
        sa.Column("template_content", sa.LargeBinary(), nullable=True),
    )


def downgrade():
    op.drop_column("cv_generated_documents", "consent_content")
    op.drop_column("cv_generated_documents", "template_content")
