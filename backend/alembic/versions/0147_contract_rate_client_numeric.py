"""Convert contracts.rate_client and contracts.margin to Numeric(10,2).

Niektórzy klienci (np. VeloBank) mają godzinowe stawki klienta z groszami
(206.25, 162.50, 112.50). Kolumna była INTEGER → traciła część dziesiętną.
rate_candidate zostaje INTEGER (stawki kandydata są całkowite). margin też
przechodzi na Numeric bo = rate_client - rate_candidate.

Revision ID: 0147_contract_rate_client_numeric
Revises: 0146_candidate_fk_cascade_sweep
Create Date: 2026-06-26
"""

from alembic import op
import sqlalchemy as sa

revision = "0147_contract_rate_client_numeric"
down_revision = "0146_candidate_fk_cascade_sweep"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "contracts",
        "rate_client",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
    )
    op.alter_column(
        "contracts",
        "margin",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "contracts",
        "margin",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="round(margin)::integer",
    )
    op.alter_column(
        "contracts",
        "rate_client",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="round(rate_client)::integer",
    )
