"""Historia stawek kontraktu z faktur KSeF (decyzje Artura 25.11.2026).

Revision ID: 0781_contract_rate_history_ksef
Revises: 0780_client_cv_file_format

Tabela ``contract_rate_history_findings`` — kroki stawki klienta i kosztowej
wyprowadzone z faktur sprzedaży i faktur konsultantów w KSeF, których nie ma
w harmonogramie kontraktu, i decyzja (wpis automatyczny historii, wpis
człowieka, odrzucenie, cofnięcie). DDL ma jedno źródło
(``app/services/contract_rate_history/schema_sql.py``); entrypoint wykonuje je
przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services.contract_rate_history import schema_sql as schema

revision = "0781_contract_rate_history_ksef"
down_revision = "0780_client_cv_file_format"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
