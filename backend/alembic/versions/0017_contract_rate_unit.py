"""Phase 9 A3: add rate_unit + billing_hours_per_month to contracts

Revision ID: 0017
Revises: 0016
Create Date: 2026-04-17 12:00:00.000000

Rationale: existing contracts store rate as opaque Integer with an implicit
monthly unit; reports did `rate * 160 hours` blanket-multiplication. For
staffing B2B/UoP/UoD we need to know whether a rate is hourly/daily/monthly
and (for hourly rates) how many hours a month the contractor bills.

Adds:
    contracts.rate_unit: ENUM('hourly','daily','monthly') NOT NULL DEFAULT 'monthly'
    contracts.billing_hours_per_month: INTEGER NOT NULL DEFAULT 160
"""

from alembic import op
import sqlalchemy as sa


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # NOTE: 0001_initial uses Base.metadata.create_all(), which already creates the
    # current model's columns when starting from scratch. This migration therefore
    # must be idempotent so CI fresh-bootstrap and existing DBs both converge.
    bind = op.get_bind()

    # Enum — Enum.create(checkfirst=True) is already idempotent.
    rate_unit_enum = sa.Enum("hourly", "daily", "monthly", name="rateunit")
    rate_unit_enum.create(bind, checkfirst=True)

    # Columns — use IF NOT EXISTS (Postgres 9.6+).
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS rate_unit rateunit NOT NULL DEFAULT 'monthly'"
    )
    op.execute(
        "ALTER TABLE contracts "
        "ADD COLUMN IF NOT EXISTS billing_hours_per_month INTEGER NOT NULL DEFAULT 160"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS billing_hours_per_month")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS rate_unit")
    sa.Enum(name="rateunit").drop(op.get_bind(), checkfirst=True)
