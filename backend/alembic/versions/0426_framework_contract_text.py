"""Treść umów ramowych klientów dla Jarvisa (09.10.2026).

Revision ID: 0426_framework_contract_text
Revises: 0425_daily_digest_opt_out

Jarvis na pytanie o zapis umowy z klientem odpowiadał, że nie ma dostępu do
treści umów — plik leżał w NEXUSIE, ale nikt go nie czytał. Tabela
``client_framework_contract_chunks`` trzyma tekst umowy we fragmentach,
a kolumny ``client_framework_contracts.text_*`` stan odczytu pliku.

SQL ma jedno źródło (``app/services/framework_contract_text_schema.py``) — ten
sam moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import framework_contract_text_schema as schema

revision = "0426_framework_contract_text"
down_revision = "0425_daily_digest_opt_out"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Fragmenty są danymi pochodnymi — odbudowuje je odczyt pliku umowy.
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
