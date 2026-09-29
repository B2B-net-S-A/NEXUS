"""Dokumenty kontraktów z folderu „Umowy pracowników” na SharePoincie (ticket 9).

Revision ID: 0402_contract_docs_sharepoint
Revises: 0401_b2b_annex_rates

Przebiegi pierwszego pobrania (podgląd → zapis → cofnięcie), stan plików
synchronizacji SharePoint ↔ NEXUS i nowe kolumny ``contract_documents``
(skrót treści, źródło, powiązanie z plikiem w SharePoincie). DDL ma jedno
źródło z siatką w ``entrypoint.sh`` (``services/contract_folder_docs/schema_sql.py``).
"""

from alembic import op

from app.services.contract_folder_docs.schema_sql import DOWNGRADE_DDL, TABLE_DDL

revision = "0402_contract_docs_sharepoint"
down_revision = "0401_b2b_annex_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    # Cofnięcie przy istniejących dokumentach z SharePointa kasowałoby ich
    # pochodzenie — odmawiamy (wzór: 0381/0383/0388).
    bind = op.get_bind()
    imported = bind.exec_driver_sql(
        "SELECT count(*) FROM contract_documents WHERE source IN "
        "('sharepoint', 'sharepoint_import')"
    ).scalar()
    if imported:
        raise RuntimeError(
            "0402 downgrade refused: contract_documents has SharePoint documents"
        )
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
