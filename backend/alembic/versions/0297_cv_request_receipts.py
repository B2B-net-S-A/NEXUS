"""Idempotent CV enqueue receipts; no historical request keys are invented."""

from alembic import op
import sqlalchemy as sa

revision = "0297_cv_request_receipts"
down_revision = "0296_cv_version_assets"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cv_generation_requests",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("request_key", sa.String(36), nullable=False),
        sa.Column("request_sha256", sa.String(64), nullable=False),
        sa.Column(
            "generated_id",
            sa.Integer(),
            sa.ForeignKey("cv_generated_documents.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.UniqueConstraint("user_id", "request_key", name="uq_cv_generation_request"),
    )


def downgrade():
    op.drop_table("cv_generation_requests")
