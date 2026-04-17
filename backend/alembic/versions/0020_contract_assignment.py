"""Phase 9 B5: contract assignment / deployment context

Revision ID: 0020
Revises: 0019
Create Date: 2026-04-17 15:00:00.000000

Adds columns describing where the contractor is embedded on the client side:
client PM, work mode (remote/hybrid/onsite), office, team, project name.
"""

from alembic import op
import sqlalchemy as sa


revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    work_mode = sa.Enum("remote", "hybrid", "onsite", name="contractworkmode")
    work_mode.create(bind, checkfirst=True)

    # All columns nullable — existing rows get NULL which is fine.
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS client_pm_name VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS client_pm_email VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS work_mode contractworkmode"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS office_location VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS team_name VARCHAR(255)"
    )
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS project_name VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS project_name")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS team_name")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS office_location")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS work_mode")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS client_pm_email")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS client_pm_name")
    sa.Enum(name="contractworkmode").drop(op.get_bind(), checkfirst=True)
