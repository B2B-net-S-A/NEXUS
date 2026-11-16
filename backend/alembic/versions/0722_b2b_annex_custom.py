"""Aneks z własną nazwą w Generatorze aneksów (16.11.2026).

Revision ID: 0722_b2b_annex_custom
Revises: 0720_finance_archive

Typ ``annex_custom`` w CHECK ``ck_b2b_contract_documents_type`` i wartość
``custom_change`` w ``contractamendmenttype`` (wpis w zakładce „Aneksy”
kontraktu po podpisie). DDL ma jedno źródło z siatką w ``entrypoint.sh``
(``services/b2b_documents/schema_sql.py``).

Downgrade wraca do listy typów sprzed 0722 jako ``NOT VALID`` (wydane aneksy
zostają w tabeli); wartość enuma zostaje, bo Postgres nie ma ``DROP VALUE``.
"""

from alembic import op

from app.services.b2b_documents.schema_sql import (
    ENUM_DDL,
    TYPE_CHECK_DDL,
    TYPES_BEFORE_0722,
)

revision = "0722_b2b_annex_custom"
down_revision = "0720_finance_archive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in ENUM_DDL:
            op.execute(statement)
    for statement in TYPE_CHECK_DDL:
        op.execute(statement)


def downgrade() -> None:
    allowed = ", ".join(f"'{t}'" for t in TYPES_BEFORE_0722)
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "DROP CONSTRAINT IF EXISTS ck_b2b_contract_documents_type"
    )
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "ADD CONSTRAINT ck_b2b_contract_documents_type "
        f"CHECK (document_type IN ({allowed})) NOT VALID"
    )
