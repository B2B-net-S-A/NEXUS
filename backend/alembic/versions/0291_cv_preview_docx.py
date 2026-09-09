"""Store exact rule preview DOCX artifacts for comparison."""

from alembic import op
import sqlalchemy as sa

revision = "0291_cv_preview_docx"
down_revision = "0290_cv_generation_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "client_cv_rule_previews",
        sa.Column("with_rule_docx", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "client_cv_rule_previews",
        sa.Column("without_rule_docx", sa.LargeBinary(), nullable=True),
    )


def downgrade():
    op.drop_column("client_cv_rule_previews", "without_rule_docx")
    op.drop_column("client_cv_rule_previews", "with_rule_docx")
