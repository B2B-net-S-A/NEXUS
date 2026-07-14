"""Add complete vector-space identity to embedding cache.

Revision ID: 0167_embedding_cache_identity
Revises: 0166_ai_control_plane
"""

from alembic import op
import sqlalchemy as sa


revision = "0167_embedding_cache_identity"
down_revision = "0166_ai_control_plane"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "embedding_cache",
        sa.Column("provider", sa.String(32), nullable=False, server_default="voyage"),
    )
    op.add_column(
        "embedding_cache",
        sa.Column(
            "text_schema", sa.String(32), nullable=False, server_default="legacy_v1"
        ),
    )


def downgrade() -> None:
    op.drop_column("embedding_cache", "text_schema")
    op.drop_column("embedding_cache", "provider")
