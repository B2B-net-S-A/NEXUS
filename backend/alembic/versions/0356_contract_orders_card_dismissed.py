"""Usunięcie pustej karty szkicu z zakładki Zamówienia (ticket 09.2026, C1).

Revision ID: 0356_contract_orders_card_dismissed
Revises: 0354_order_change_checks

Karta kontraktora w zakładce Zamówienia jest liczona z KONTRAKTU, więc po
usunięciu jedynego zamówienia zostawała pusta karta „Brak aktywnego
zamówienia", której nie dało się usunąć — kontraktu (i danych rekrutacji)
kasować nie wolno. ``orders_card_dismissed_at`` chowa tę kartę; zamówienie
założone dla kontraktu PÓŹNIEJ pokazuje ją z powrotem.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony).
"""

from alembic import op

revision = "0356_contract_orders_card_dismissed"
down_revision = "0354_order_change_checks"
branch_labels = None
depends_on = None

DISMISSED_AT = (
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS "
    "orders_card_dismissed_at TIMESTAMPTZ NULL"
)
DISMISSED_BY = (
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS "
    "orders_card_dismissed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL"
)


def upgrade() -> None:
    op.execute(DISMISSED_AT)
    op.execute(DISMISSED_BY)


def downgrade() -> None:
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS orders_card_dismissed_by")
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS orders_card_dismissed_at")
