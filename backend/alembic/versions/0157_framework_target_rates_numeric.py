"""Stawka ramowa + widełki docelowe: INTEGER → NUMERIC(12,2) (grosze).

Revision ID: 0157_framework_target_rates_numeric
Revises: 0156_candidate_match_justifications
Create Date: 2026-07-10

Pole „Stawka z umowy ramowej" (``contracts.framework_rate``) oraz „Widełki
docelowe" (``target_rate_min`` / ``target_rate_max``) były INTEGER — próba
zapisania stawki z groszami (np. 215,60) kończyła się 422 na schemacie
(Pydantic ``int`` odrzuca część ułamkową, nie zaokrągla). Stawki klienckie z
umów ramowych rutynowo mają grosze, więc poszerzamy do ``NUMERIC(12,2)`` —
analogicznie do migracji 0147/0148 dla rate_candidate/rate_client.

INTEGER → NUMERIC tylko dodaje precyzję; istniejące wartości bez zmian
(215 → 215,00). Bezpieczny natychmiastowy ALTER (tabela mała). Downgrade
zaokrągla do pełnych złotych.

Idempotentna względem safety-netu w ``entrypoint.sh`` (ten sam ALTER; ponowne
wykonanie NUMERIC→NUMERIC to no-op semantyczny).
"""

import sqlalchemy as sa
from alembic import op

revision = "0157_framework_target_rates_numeric"
down_revision = "0156_candidate_match_justifications"
branch_labels = None
depends_on = None


_COLUMNS = ("framework_rate", "target_rate_min", "target_rate_max")


def upgrade() -> None:
    for column in _COLUMNS:
        op.alter_column(
            "contracts",
            column,
            existing_type=sa.Integer(),
            type_=sa.Numeric(12, 2),
            existing_nullable=True,
        )


def downgrade() -> None:
    for column in _COLUMNS:
        op.alter_column(
            "contracts",
            column,
            existing_type=sa.Numeric(12, 2),
            type_=sa.Integer(),
            existing_nullable=True,
            postgresql_using=f"round({column})::integer",
        )
