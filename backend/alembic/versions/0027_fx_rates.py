"""Phase 9 C4: fx_rates cache table

Revision ID: 0027
Revises: 0026
Create Date: 2026-04-17 18:30:00.000000

Daily NBP FX rates → PLN, cached by (effective_date, currency).
"""

from alembic import op


revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS fx_rates (
            id SERIAL PRIMARY KEY,
            effective_date DATE NOT NULL,
            currency VARCHAR(3) NOT NULL,
            rate_to_pln NUMERIC(14, 6) NOT NULL,
            source VARCHAR(32) NOT NULL DEFAULT 'NBP',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    # Idempotent backfill for environments that already ran an earlier draft.
    op.execute(
        "ALTER TABLE fx_rates ADD COLUMN IF NOT EXISTS updated_at "
        "TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_fx_rates_date_currency "
        "ON fx_rates(effective_date, currency)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS fx_rates CASCADE")
