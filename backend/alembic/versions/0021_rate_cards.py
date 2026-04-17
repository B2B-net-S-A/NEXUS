"""Phase 9 B2: rate_cards table

Revision ID: 0021
Revises: 0020
Create Date: 2026-04-17 15:30:00.000000

Price list per client × role × seniority. Used by:
- Auto-suggest in contract create/edit modal
- Auto-hire flow prefill
"""

from alembic import op
import sqlalchemy as sa


revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS rate_cards (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL
                REFERENCES clients(id) ON DELETE CASCADE,
            role VARCHAR(255) NOT NULL,
            seniority VARCHAR(32),
            rate_candidate_min INTEGER,
            rate_candidate_max INTEGER,
            rate_client_min INTEGER,
            rate_client_max INTEGER,
            currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
            rate_unit rateunit NOT NULL DEFAULT 'monthly',
            valid_from DATE,
            valid_to DATE,
            notes TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rate_cards_client_id "
        "ON rate_cards(client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_rate_cards_role_seniority "
        "ON rate_cards(role, seniority)"
    )
    # Unique guard: nie ma sensu mieć dwóch aktywnych cenników dla tego samego
    # klient × rola × seniority × valid_from.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_rate_cards_client_role_seniority_valid_from "
        "ON rate_cards(client_id, role, COALESCE(seniority, ''), COALESCE(valid_from, DATE '1900-01-01'))"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS rate_cards CASCADE")
