"""Durable cleanup for explicitly deleted CV source owners; no historical sweep."""

from alembic import op
import sqlalchemy as sa

revision = "0301_cv_source_cleanup"
down_revision = "0300_cv_approval_jobs"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cv_source_cleanup",
        sa.Column("storage_key", sa.String(500), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_cv_source_cleanup_next_attempt_at", "cv_source_cleanup", ["next_attempt_at"]
    )


def downgrade():
    op.drop_table("cv_source_cleanup")
