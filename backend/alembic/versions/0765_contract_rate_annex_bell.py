"""Dzwonek Finansów o kroku stawki konsultanta z aneksu („stawka od dnia”).

Revision ID: 0765_contract_rate_annex_bell
Revises: 0764_contractor_payment_blocks

Przegląd skrzynki umowy@ (23.11.2026): zmiana stawki trafiała do Rozliczeń
tylko jako PDF aneksu mailem. Typ ``contract_rate_annex`` niesie dzwonek
Finansów z ``services/contract_rate_annex_signal.py``. Lustro w
``entrypoint.sh`` (``_ENUM_STATEMENTS``).
"""

from alembic import op

revision = "0765_contract_rate_annex_bell"
down_revision = "0764_contractor_payment_blocks"
branch_labels = None
depends_on = None

NOTIFICATION_TYPE = "contract_rate_annex"


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
        RAISE EXCEPTION 'Downgrade 0765 odmawia: notifications ma wpisy {NOTIFICATION_TYPE}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
