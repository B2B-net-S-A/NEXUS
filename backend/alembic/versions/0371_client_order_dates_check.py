"""Zamówienie klienta: data końca nie przed datą startu (audyt 24.09.2026, S7).

Revision ID: 0371_client_order_dates_check
Revises: 0370_teams_prep_transcripts

Grupy zamówień mają ``ck_client_order_groups_dates`` od początku, pojedyncze
zamówienia nie miały żadnego więzu — formularze przyjmowały koniec przed
startem, a reguły „kończy się / następca / brak" liczyły wtedy nonsens.

``NOT VALID`` świadomie: produkcja ma historyczne zamówienie z odwróconym
okresem (653). Więz obowiązuje dla NOWYCH zapisów i zmian dat, bez skanowania
tabeli i bez wywracania deployu; API odpowiada czytelnym 422
(``client_orders._assert_order_period``). ``VALIDATE CONSTRAINT`` — dopiero po
ręcznym poprawieniu starych danych.

Lustro w ``entrypoint.sh`` (``_CONSTRAINT_STATEMENTS``) — prod alembic bywa
osierocony; pilnuje ``test_client_order_dates_check_mirror.py``.
"""

from alembic import op

revision = "0371_client_order_dates_check"
down_revision = "0370_teams_prep_transcripts"
branch_labels = None
depends_on = None

ADD_CHECK = """DO $$ BEGIN
    ALTER TABLE client_orders
        ADD CONSTRAINT ck_client_orders_dates
        CHECK (start_date IS NULL OR end_date IS NULL OR end_date >= start_date)
        NOT VALID;
EXCEPTION WHEN duplicate_object THEN NULL; END $$"""


def upgrade() -> None:
    op.execute(ADD_CHECK)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS ck_client_orders_dates"
    )
