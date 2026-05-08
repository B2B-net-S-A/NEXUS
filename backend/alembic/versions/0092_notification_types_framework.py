"""Dodaj 6 nowych wartości do enum notificationtype dla framework contracts + orders.

Revision ID: 0092_notification_types_framework
Revises: 0091_extend_document_signature_msa
Create Date: 2026-05-08 16:25:00.000000

Per memory `project_kpi_coach_enum_gotcha`: ALTER TYPE … ADD VALUE wymaga
autocommit_block (nie może być wewnątrz transakcji).

`client_order_ending_30d` JUŻ istnieje (z migracji 0037), tutaj dokładamy
14d i 7d dla escalation.
"""

from alembic import op


revision = "0092_notification_types_framework"
down_revision = "0091_extend_document_signature_msa"
branch_labels = None
depends_on = None


NEW_VALUES = [
    "framework_contract_expiring_30d",
    "framework_contract_expiring_14d",
    "framework_contract_expiring_7d",
    "framework_contract_signed",
    "client_order_ending_14d",
    "client_order_ending_7d",
]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in NEW_VALUES:
            op.execute(
                f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
            )


def downgrade() -> None:
    # PG nie wspiera DROP VALUE z enum bez rekreacji typu — zostawiamy.
    pass
