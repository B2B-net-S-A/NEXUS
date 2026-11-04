"""Umowa o udziale w procesie rekrutacyjnym — dwa nowe typy dokumentu (21.10.2026).

Revision ID: 0503_b2b_document_participation_types
Revises: 0501_scoring_weight_changes

``preliminary_participation_jdg`` i ``preliminary_participation_person``
w CHECK ``ck_b2b_contract_documents_type``. DDL ma jedno źródło z siatką
w ``entrypoint.sh`` (``services/b2b_documents/schema_sql.py``).

Downgrade wraca do listy sprzed 0503 jako ``NOT VALID``: wydane już umowy
o udziale w rekrutacji zostają w tabeli (nie kasujemy dokumentów), a więz
pilnuje tylko nowych wierszy.
"""

from alembic import op

from app.services.b2b_documents.schema_sql import (
    TYPE_CHECK_DDL,
    TYPES_BEFORE_0503,
)

revision = "0503_b2b_document_participation_types"
down_revision = "0501_scoring_weight_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TYPE_CHECK_DDL:
        op.execute(statement)


def downgrade() -> None:
    allowed = ", ".join(f"'{t}'" for t in TYPES_BEFORE_0503)
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "DROP CONSTRAINT IF EXISTS ck_b2b_contract_documents_type"
    )
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "ADD CONSTRAINT ck_b2b_contract_documents_type "
        f"CHECK (document_type IN ({allowed})) NOT VALID"
    )
