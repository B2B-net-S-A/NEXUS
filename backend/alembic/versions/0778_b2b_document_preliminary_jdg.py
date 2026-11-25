"""Umowy przedwstępne z kandydatem prowadzącym działalność (25.11.2026).

Revision ID: 0778_b2b_document_preliminary_jdg
Revises: 0777_claim_handover

Typy ``preliminary_cez_jdg`` i ``preliminary_b2b_jdg`` (rodzina
``preliminary``) w CHECK ``ck_b2b_contract_documents_type``. DDL ma jedno
źródło z siatką w ``entrypoint.sh`` (``services/b2b_documents/schema_sql.py``).

Downgrade wraca do listy typów sprzed 0778 jako ``NOT VALID`` (wydane umowy
zostają w tabeli).
"""

from alembic import op

from app.services.b2b_documents.schema_sql import (
    TYPE_CHECK_DDL,
    TYPES_BEFORE_PRELIMINARY_JDG,
)

revision = "0778_b2b_document_preliminary_jdg"
down_revision = "0777_claim_handover"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TYPE_CHECK_DDL:
        op.execute(statement)


def downgrade() -> None:
    allowed = ", ".join(f"'{t}'" for t in TYPES_BEFORE_PRELIMINARY_JDG)
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "DROP CONSTRAINT IF EXISTS ck_b2b_contract_documents_type"
    )
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "ADD CONSTRAINT ck_b2b_contract_documents_type "
        f"CHECK (document_type IN ({allowed})) NOT VALID"
    )
