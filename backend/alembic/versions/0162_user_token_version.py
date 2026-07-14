"""Add per-user JWT revocation version.

Revision ID: 0162_user_token_version
Revises: 0161_reconcile_startup_schema
"""

from alembic import op
import sqlalchemy as sa


revision = "0162_user_token_version"
down_revision = "0161_reconcile_startup_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "token_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_users_token_version_nonnegative",
        "users",
        "token_version >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_token_version_nonnegative",
        "users",
        type_="check",
    )
    op.drop_column("users", "token_version")
