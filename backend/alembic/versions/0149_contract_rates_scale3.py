"""Stawki kontraktów: NUMERIC(10,2) → NUMERIC(12,3) (ułamkowe stawki/h, 3 miejsca).

Revision ID: 0149_contract_rates_scale3
Revises: 0148_candidate_rate_numeric
Create Date: 2026-06-26

Migracje 0147/0148 zamieniły pola stawek z INTEGER na ``NUMERIC(10,2)`` (grosze
/ połówki). Część zamówień klientów ma jednak stawkę godzinową z **trzema**
miejscami po przecinku (np. Alior: 164,375 / 141,175 / 194,375 / 161,875 zł/h) —
skala 2 zaokrąglałaby je (164,375 → 164,38), gubiąc wierność z zamówieniem.

Poszerza skalę do 3 (``NUMERIC(12,3)``) na kolumnach stawek:

  * ``contracts.rate_candidate`` / ``rate_client`` / ``margin``
  * ``contract_candidate_rates.rate``
  * ``candidate_rate_history.rate``
  * ``client_orders.rate_client``

NUMERIC(10,2) → NUMERIC(12,3) tylko DODAJE precyzję (skala rośnie, precyzja
rośnie) — istniejące wartości pozostają bez zmian (164,38 → 164,380). Bezpieczny,
natychmiastowy ALTER (tabele małe). Downgrade zwęża z powrotem do skali 2
(``round`` do 2 miejsc).
"""

import sqlalchemy as sa
from alembic import op

revision = "0149_contract_rates_scale3"
down_revision = "0148_candidate_rate_numeric"
branch_labels = None
depends_on = None


# (table, column, nullable)
_RATE_COLUMNS = (
    ("contracts", "rate_candidate", True),
    ("contracts", "rate_client", True),
    ("contracts", "margin", True),
    ("contract_candidate_rates", "rate", False),
    ("candidate_rate_history", "rate", False),
    ("client_orders", "rate_client", True),
)


def upgrade() -> None:
    for table, column, nullable in _RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(10, 2),
            type_=sa.Numeric(12, 3),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    for table, column, nullable in _RATE_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(12, 3),
            type_=sa.Numeric(10, 2),
            existing_nullable=nullable,
            postgresql_using=f"round({column}, 2)::numeric(10,2)",
        )
