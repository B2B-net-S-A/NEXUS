"""Zamówienia: waluta sprzed zmiany w dzienniku (audyt 24.09.2026).

Revision ID: 0371_order_dates_and_currency_audit
Revises: 0370_teams_prep_transcripts

S7 — okres zamówienia (koniec nie przed startem) pilnuje API (422,
``client_orders._assert_order_period``) i formularze, NIE więz w bazie:
``CHECK … NOT VALID`` Postgres sprawdza przy KAŻDYM UPDATE wiersza, więc
historyczne zamówienie z odwróconym okresem (653) blokowałoby każdy jego
zapis, a masowy UPDATE nocnego skanera wycofywałby cały przebieg.

N1 — ``order_change_events.old_currency``: sama zmiana waluty stawki
(1000 PLN → 1000 EUR) też jest zmianą pieniędzy; dziennik jej nie widział.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_order_dates_and_currency_audit_mirror.py``.
"""

from alembic import op

revision = "0371_order_dates_and_currency_audit"
down_revision = "0370_teams_prep_transcripts"
branch_labels = None
depends_on = None

ADD_OLD_CURRENCY = (
    "ALTER TABLE order_change_events ADD COLUMN IF NOT EXISTS old_currency VARCHAR(3)"
)


def upgrade() -> None:
    op.execute(ADD_OLD_CURRENCY)


def downgrade() -> None:
    op.execute("ALTER TABLE order_change_events DROP COLUMN IF EXISTS old_currency")
    op.execute(
        "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS ck_client_orders_dates"
    )
