"""Foldery w zakładce Dokumenty kontraktu (ticket Ani, 21.10.2026).

Revision ID: 0494_contract_document_folders
Revises: 0493_cost_consumption_manual_entry

Tabela ``contract_document_folders`` i kolumna ``contract_documents.folder_id``
(``ON DELETE SET NULL`` — usunięcie folderu oddaje pliki na listę główną).
Folder „Zamówienia” wynika z typu dokumentu, więc migracja nie przenosi
żadnych danych. DDL ma jedno źródło z siatką w ``entrypoint.sh``
(``services/contract_document_folders_schema.py``).
"""

from alembic import op

from app.services.contract_document_folders_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0494_contract_document_folders"
down_revision = "0493_cost_consumption_manual_entry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
