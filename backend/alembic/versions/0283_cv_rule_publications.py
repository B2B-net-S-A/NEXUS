"""Separate CV rule drafts from published recipes.

Revision ID: 0283_cv_rule_publications
Revises: 0282_b2b_signature_permission
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0283_cv_rule_publications"
down_revision = "0282_b2b_signature_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "client_cv_rule_previews", sa.Column("recipe_snapshot", postgresql.JSONB())
    )
    op.add_column("client_cv_rules", sa.Column("draft_payload", postgresql.JSONB()))
    op.add_column(
        "client_cv_rules",
        sa.Column("edit_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "client_cv_rule_publications",
        sa.Column(
            "client_id",
            sa.Integer(),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("recipe", postgresql.JSONB(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "published_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")
        ),
    )
    # Preserve the currently effective recipe without activating any seed.
    op.execute("""
        INSERT INTO client_cv_rule_publications
            (client_id, version, recipe, published_at, published_by)
        SELECT r.client_id, r.version,
            (to_jsonb(r) - ARRAY['id', 'client_id', 'version', 'seed_key',
                'confirmed_at', 'confirmed_by', 'created_at', 'updated_at',
                'draft_payload', 'edit_revision']) || jsonb_build_object(
                    'cv_content_mode_cap', c.cv_content_mode_cap,
                    'cv_interactive_enabled', c.cv_interactive_enabled),
            r.confirmed_at, r.confirmed_by
        FROM client_cv_rules r JOIN clients c ON c.id = r.client_id
        WHERE r.confirmed_at IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_column("client_cv_rule_previews", "recipe_snapshot")
    op.drop_table("client_cv_rule_publications")
    op.drop_column("client_cv_rules", "edit_revision")
    op.drop_column("client_cv_rules", "draft_payload")
