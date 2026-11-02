"""Licznik użycia obszarów do przeglądu najmniejszych dostępów.

Revision ID: 0630_access_usage_daily
Revises: 0629_company_results_permission

Program najmniejszych dostępów (Artur 02.11.2026): odczyty ekranów nie są nigdzie
logowane, więc bez pomiaru nie da się uczciwie zdecydować, komu odebrać odczyt.
Tabela powstaje od razu, a zbieranie włącza dopiero
``ACCESS_USAGE_COUNTER_ENABLED`` po decyzji Artura. DDL
w ``app/services/access_usage_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.access_usage_schema import TABLE_DDL

revision = "0630_access_usage_daily"
down_revision = "0629_company_results_permission"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS access_usage_daily")
