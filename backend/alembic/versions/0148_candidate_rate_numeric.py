"""Stawka kandydata → Numeric(10,2) + scalenie dwóch headów 0147.

Revision ID: 0148_candidate_rate_numeric
Revises: 0147_contract_rate_client_numeric, 0147_client_order_rate_decimal
Create Date: 2026-06-26

Migracje 0147 (VeloBank #593, Polkomtel #594) przeszły na ``Numeric(10,2)``
stawkę KLIENTA (``contracts.rate_client``, ``contracts.margin``,
``client_orders.rate_client``), ale stawka KANDYDATA została ``Integer``.
Import zamówień Erste ma kandydata ze stawką godzinową z połówką
(``157.5 PLN/h``) — nie da się jej zapisać jako Integer.

Ta migracja:
  * scala dwa równoległe heady 0147 w jeden (down_revision = krotka), oraz
  * przełącza rodzinę stawki kandydata na ``Numeric(10,2)`` — symetrycznie do
    tego, co 0147 zrobiło dla stawki klienta:
      - ``contracts.rate_candidate``
      - ``contract_candidate_rates.rate`` (harmonogram stawki kandydata)
      - ``candidate_rate_history.rate`` (historia stawek)

Konwersja int→numeric jest bezstratna i wykonuje się in-place. Downgrade
zaokrągla numeric→integer (USING round) — potencjalnie stratny.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0148_candidate_rate_numeric"
down_revision: tuple[str, str] = (
    "0147_contract_rate_client_numeric",
    "0147_client_order_rate_decimal",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (table, column, nullable)
_CANDIDATE_RATE_COLUMNS: list[tuple[str, str, bool]] = [
    ("contracts", "rate_candidate", True),
    ("contract_candidate_rates", "rate", False),
    ("candidate_rate_history", "rate", False),
]


def upgrade() -> None:
    for table, column, nullable in _CANDIDATE_RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Integer(),
            type_=sa.Numeric(10, 2),
            existing_nullable=nullable,
            postgresql_using=f"{column}::numeric(10,2)",
        )


def downgrade() -> None:
    for table, column, nullable in _CANDIDATE_RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(10, 2),
            type_=sa.Integer(),
            existing_nullable=nullable,
            postgresql_using=f"round({column})::integer",
        )
