"""Zamówienia: CHECK okresu i waluta sprzed zmiany w dzienniku (audyt 24.09.2026).

Revision ID: 0371_order_dates_and_currency_audit
Revises: 0370_teams_prep_transcripts

S7 — ``ck_client_orders_dates``: data końca zamówienia nie przed datą startu.
Grupy zamówień mają ``ck_client_order_groups_dates`` od początku, pojedyncze
zamówienia nie miały żadnego więzu — formularze przyjmowały koniec przed
startem, a reguły „kończy się / następca / brak" liczyły wtedy nonsens.
``NOT VALID`` świadomie: produkcja ma historyczne zamówienie z odwróconym
okresem (653). Więz obowiązuje dla NOWYCH zapisów i zmian dat, bez skanowania
tabeli i bez wywracania deployu; API odpowiada czytelnym 422
(``client_orders._assert_order_period``). ``VALIDATE CONSTRAINT`` — dopiero po
ręcznym poprawieniu starych danych.

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

ADD_CHECK = """DO $$ BEGIN
    ALTER TABLE client_orders
        ADD CONSTRAINT ck_client_orders_dates
        CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$"""

ADD_OLD_CURRENCY = (
    "ALTER TABLE order_change_events ADD COLUMN IF NOT EXISTS old_currency VARCHAR(3)"
)


def upgrade() -> None:
    op.execute(ADD_CHECK)
    op.execute(ADD_OLD_CURRENCY)


def downgrade() -> None:
    op.execute("ALTER TABLE order_change_events DROP COLUMN IF EXISTS old_currency")
    op.execute(
        "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS ck_client_orders_dates"
    )
