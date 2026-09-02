"""Add the Talent Community Manager application role.

Revision ID: 0267_talent_community_manager
Revises: 0266_cv_rules_generator_instructions
Create Date: 2026-09-02
"""

from alembic import op


revision = "0267_talent_community_manager"
down_revision = "0266_cv_rules_generator_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL requires ADD VALUE to commit before the value can be used by
    # later statements. This migration only expands the enum; no account is
    # assigned automatically.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'talent_community_manager'"
        )


def downgrade() -> None:
    # PostgreSQL cannot safely remove one enum value in place. The expand is
    # intentionally forward-only; downgrading application code leaves the
    # unused value harmlessly present.
    pass
