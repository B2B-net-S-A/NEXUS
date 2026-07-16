"""Finanse (plan PR 6): client_orders.filled_at + financial_adjustments.

- ``client_orders.filled_at`` — FAKT pierwszej aktywacji zamówienia.
  Historyczne wiersze pozostają NULL (raporty oznaczają je jako partial,
  zakaz estymowania — plan PR 6 pkt 12).
- ``financial_adjustments`` — niemutowalny rejestr korekt (draft→approved,
  admin-only write, admin/DL read).

Lustro w backend/entrypoint.sh (multi-head trap).

Revision ID: 0176_finance_filled_at_adjustments
Revises: 0175_analytics_milestones_acceptance
"""

from alembic import op

revision = "0176_finance_filled_at_adjustments"
down_revision = "0175_analytics_milestones_acceptance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS filled_at TIMESTAMPTZ"
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE adjustmentstatus AS ENUM ('draft', 'approved');
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS financial_adjustments (
            id              SERIAL PRIMARY KEY,
            effective_month DATE NOT NULL,
            kind            VARCHAR(50) NOT NULL,
            amount          NUMERIC(14, 2) NOT NULL,
            currency        VARCHAR(3) NOT NULL DEFAULT 'PLN',
            description     TEXT NOT NULL,
            client_id       INTEGER REFERENCES clients(id) ON DELETE SET NULL,
            status          adjustmentstatus NOT NULL DEFAULT 'draft',
            created_by      INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            approved_by     INTEGER REFERENCES users(id) ON DELETE RESTRICT,
            approved_at     TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_month "
        "ON financial_adjustments (effective_month)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_status "
        "ON financial_adjustments (status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_financial_adjustments_client "
        "ON financial_adjustments (client_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS financial_adjustments")
    op.execute("DROP TYPE IF EXISTS adjustmentstatus")
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS filled_at")
