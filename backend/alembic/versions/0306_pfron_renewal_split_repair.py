"""PFRON 507–509: rozdzielenie zamówień nadpisanych „reaktywacją” z maila.

Revision ID: 0306_pfron_renewal_split_repair
Revises: 0305_candidate_search_retention_indexes

Korekta danych bez zmiany schematu. W nocy 9/10.09.2026 jednorazowe
czyszczenie kolejki zamówień z maila przepisało W MIEJSCU trzy zakończone
zamówienia PFRON (507, 508, 509) nowym okresem 01.09–30.11.2026. Writer jest
już poprawiony (powrót po przerwie = nowe zamówienie); ta migracja odtwarza
historię z Activity ``order_mail_reactivate``: nowy okres przechodzi do
nowego wiersza, oryginał wraca do stanu sprzed nadpisania. Zamówienia są
przypięte pełną tożsamością biznesową — niespełniony warunek zostawia
zamówienie bez zmian z powodem w paragonie ``app_settings``. Jedno źródło
SQL-a w ``app/services/pfron_renewal_split_repair.py`` (lustro w
``entrypoint.sh``). ``downgrade`` nie odtworzy stanu nadpisanego: brak.
"""

from alembic import op

from app.services.pfron_renewal_split_repair import PFRON_RENEWAL_SPLIT_SQL

revision = "0306_pfron_renewal_split_repair"
down_revision = "0305_candidate_search_retention_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(PFRON_RENEWAL_SPLIT_SQL)


def downgrade() -> None:
    pass
