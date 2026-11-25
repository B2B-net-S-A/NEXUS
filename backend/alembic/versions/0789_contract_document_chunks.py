"""Treść podpisanych dokumentów kontraktu do odczytu (asystent prawny E, 25.11.2026).

Revision ID: 0789_contract_document_chunks
Revises: 0788_legal_redline_ai

Tabela ``contract_document_chunks`` (fragmenty tekstu umowy, aneksu,
wypowiedzenia i porozumienia z Dokumentów kontraktu) i kolumny stanu odczytu
``contract_documents.text_*``. Same dodania — stary kod działa na nowym
schemacie. DDL ma jedno źródło z siatką w ``entrypoint.sh``
(``services/contract_document_text/schema.py``).
"""

from alembic import op

from app.services.contract_document_text.schema import ALL_DDL, DOWNGRADE_DDL

revision = "0789_contract_document_chunks"
down_revision = "0788_legal_redline_ai"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
