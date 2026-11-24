"""Dzwonek Finansów o nabywcy kontraktu Nordei z maila CPro.

Revision ID: 0766_cpro_invoice_buyer_bell
Revises: 0765_contractor_payment_blocks

Przegląd skrzynek DL-ów Nordei (24.11.2026): zmiana adresu faktury w CPro
(„Invoice address was updated”) przychodziła tylko do DL-a. Typ
``cpro_invoice_buyer`` niesie dzwonek Finansów z ``services/cpro_invoice_buyer.py``.
Lustro w ``entrypoint.sh`` (``_ENUM_STATEMENTS``).
"""

from alembic import op

revision = "0766_cpro_invoice_buyer_bell"
down_revision = "0765_contractor_payment_blocks"
branch_labels = None
depends_on = None

NOTIFICATION_TYPE = "cpro_invoice_buyer"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{NOTIFICATION_TYPE}'"
        )


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed tej
# rewizji jej nie zna — dzwonek tego typu dałby 500 przy odczycie powiadomień.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = '{NOTIFICATION_TYPE}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0766 odmawia: notifications ma wpisy {NOTIFICATION_TYPE}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
