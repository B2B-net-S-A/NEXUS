"""client_orders.rate_client → Numeric(10,2) + contracts.start_date nullable.

Motywacja: import zamówień od klienta (np. Polkomtel) gdzie stawka klienta jest
dziesiętna (np. 118.13, 218.75 PLN/h) i kolumna "Zamówienie od" bywa pusta.

- ``client_orders.rate_client``: Integer → Numeric(10,2) — przechowuje stawkę
  klienta per zamówienie z dokładnością do groszy (wstawiamy "jak w Excelu").
- ``contracts.start_date``: NOT NULL → nullable — pozwala zarejestrować kontrakt
  bez znanej daty rozpoczęcia (zamówienie bez "od").

``contracts.rate_client`` celowo zostaje Integer (stawki konsultanta/kontraktu są
całkowite); dziesiętna precyzja jest trzymana na poziomie Orderu (PO klienta).

Revision ID: 0147_client_order_rate_decimal
Revises: 0146_candidate_fk_cascade_sweep
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0147_client_order_rate_decimal"
down_revision = "0146_candidate_fk_cascade_sweep"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "client_orders",
        "rate_client",
        existing_type=sa.Integer(),
        type_=sa.Numeric(10, 2),
        existing_nullable=True,
        postgresql_using="rate_client::numeric(10,2)",
    )
    op.alter_column(
        "contracts",
        "start_date",
        existing_type=sa.Date(),
        nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "contracts",
        "start_date",
        existing_type=sa.Date(),
        nullable=False,
    )
    op.alter_column(
        "client_orders",
        "rate_client",
        existing_type=sa.Numeric(10, 2),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="round(rate_client)::integer",
    )
