"""Reuse enqueue receipts for rule previews."""

from alembic import op
import sqlalchemy as sa

revision = "0299_cv_preview_receipts"
down_revision = "0298_cv_generation_template"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "cv_generation_requests",
        sa.Column(
            "preview_id",
            sa.Integer(),
            sa.ForeignKey("client_cv_rule_previews.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )


def downgrade():
    op.drop_column("cv_generation_requests", "preview_id")
