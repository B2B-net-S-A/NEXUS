"""Jeden miesiąc roboczy: godziny rozliczeniowe 160/176 → 168 (22.09.2026).

Revision ID: 0345_billing_hours_168
Revises: 0344_competition_period_closures

Decyzja Artura po audycie statystyk: stawkę godzinową i dzienną przeliczamy
na kwotę miesięczną ZAWSZE miesiącem 21 MD × 8 h = 168 h
(``app.core.work_time``). Migracja:

* dodaje ``contracts.orders_in_md`` — fakt „zamówienia tego kontraktu są
  w MD", który do dziś niosła liczba 176 h/mc;
* zmienia domyślne ``billing_hours_per_month`` kontraktu i zamówienia na 168;
* jednorazowo (marker w ``app_settings``) przenosi znacznik 176 h do nowej
  kolumny i przepisuje 160/176 na 168 — w kontraktach i zamówieniach; każda
  inna, jawnie wybrana liczba zostaje. Żadna stawka nie jest przepisywana.

Jedno źródło SQL-a korekty: ``app/services/billing_hours_unification.py``
(lustro w ``entrypoint.sh`` — alembic na prodzie bywa osierocony).
``downgrade`` przywraca dawny znacznik (kontrakt godzinowy z ``orders_in_md``
dostaje z powrotem 176 h), zdejmuje kolumnę, domyślne 160 i marker korekty;
pozostałych godzin sprzed korekty nie odtwarza (paragon niesie same liczby).
"""

from alembic import op

from app.services.billing_hours_unification import BILLING_HOURS_UNIFICATION_SQL

revision = "0345_billing_hours_168"
down_revision = "0344_competition_period_closures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS orders_in_md "
        "BOOLEAN NOT NULL DEFAULT false"
    )
    op.execute(
        "ALTER TABLE contracts ALTER COLUMN billing_hours_per_month SET DEFAULT 168"
    )
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN billing_hours_per_month SET DEFAULT 168"
    )
    op.execute(BILLING_HOURS_UNIFICATION_SQL)


def downgrade() -> None:
    op.execute(
        "UPDATE contracts SET billing_hours_per_month = 176 "
        "WHERE orders_in_md AND rate_unit = 'hourly' "
        "AND billing_hours_per_month = 168"
    )
    op.execute("DELETE FROM app_settings WHERE key = '0345_billing_hours_168'")
    op.execute(
        "ALTER TABLE client_orders ALTER COLUMN billing_hours_per_month SET DEFAULT 160"
    )
    op.execute(
        "ALTER TABLE contracts ALTER COLUMN billing_hours_per_month SET DEFAULT 160"
    )
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS orders_in_md")
