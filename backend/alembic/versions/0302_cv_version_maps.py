"""Requirement-map attempts bound to approved CV versions; no historical backfill."""

from alembic import op
import sqlalchemy as sa

revision = "0302_cv_version_maps"
down_revision = "0301_cv_source_cleanup"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "cv_version_maps",
        sa.Column(
            "document_version_id",
            sa.Integer(),
            sa.ForeignKey("cv_document_versions.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
        sa.Column("content_sha256", sa.String(64), nullable=False),
        sa.Column("input_sha256", sa.String(64), nullable=False),
        sa.Column("input_content", sa.LargeBinary()),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("result", sa.JSON()),
        sa.Column("error_code", sa.String(64)),
        sa.Column("lease_token", sa.String(36)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'complete', 'failed', 'interrupted')",
            name="ck_cv_version_map_status",
        ),
    )
    op.create_index("ix_cv_version_maps_status", "cv_version_maps", ["status"])
    op.create_index(
        "ix_cv_version_maps_lease_expires_at", "cv_version_maps", ["lease_expires_at"]
    )


def downgrade():
    op.drop_table("cv_version_maps")
