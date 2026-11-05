"""Dokumenty do startu: lista klienta i stan dokumentów pary.

Revision ID: 0649_start_documents
Revises: 0648_consultant_panel

Decyzje Artura 05.11.2026: rekruter kończy placement z kompletem dokumentów
(NDA, KRK, PESEL), na początek bez wpływu na liczniki, ze stałymi
przypomnieniami. DDL w ``app/services/start_documents_schema.py``, lustro
w ``entrypoint.sh``.
"""

from alembic import op

from app.services.start_documents_schema import ENUM_DDL, TABLE_DDL

revision = "0649_start_documents"
down_revision = "0648_consultant_panel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in ENUM_DDL:
            op.execute(statement)
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS placement_start_documents")
    op.execute("DROP TABLE IF EXISTS client_start_documents")
