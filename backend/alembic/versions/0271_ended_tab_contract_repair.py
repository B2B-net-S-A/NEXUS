"""Reguła zakładki „Zakończeni": korekta Contract 469 + audyt klasy.

Revision ID: 0271_ended_tab_contract_repair
Revises: 0270_jobs_open_state_dates

Korekta danych bez zmiany schematu. Kod w tej samej rewizji przestaje
przepisywać datę końca ZAMÓWIENIA do daty końca UMOWY przy wskrzeszaniu
kontraktu (``sync_contract_to_live_order``) i synchronizuje zamówienia do
daty końca umowy wpisanej w module Kontrakty (``update_contract``). Ta
migracja domyka historię: wskazany w tickecie kontraktor wraca do
„Aktywnych", a analogiczne wiersze są audytowane, nie zmieniane — patrz
``app/services/contract_ended_tab_repair.py`` (jedno źródło SQL-a, lustro
w ``entrypoint.sh``). ``downgrade`` nie zna poprzedniego stanu: brak.
"""

from alembic import op

from app.services.contract_ended_tab_repair import ENDED_TAB_REPAIR_SQL

revision = "0271_ended_tab_contract_repair"
down_revision = "0270_jobs_open_state_dates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(ENDED_TAB_REPAIR_SQL)


def downgrade() -> None:
    pass
