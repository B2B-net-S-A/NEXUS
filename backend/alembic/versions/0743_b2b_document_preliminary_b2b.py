"""Umowa przedwstępna na współpracę B2B w Generatorze dokumentów (19.11.2026).

Revision ID: 0743_b2b_document_preliminary_b2b
Revises: 0742_ledger_bank_balances

Typ ``preliminary_b2b`` (rodzina ``preliminary``, każdy klient poza Centrum
e-Zdrowia) w CHECK ``ck_b2b_contract_documents_type``. DDL ma jedno źródło
z siatką w ``entrypoint.sh`` (``services/b2b_documents/schema_sql.py``).

Downgrade wraca do listy typów sprzed 0743 jako ``NOT VALID`` (wydane umowy
zostają w tabeli).
"""

from alembic import op

from app.services.b2b_documents.schema_sql import TYPE_CHECK_DDL, TYPES_BEFORE_0743

revision = "0743_b2b_document_preliminary_b2b"
down_revision = "0742_ledger_bank_balances"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TYPE_CHECK_DDL:
        op.execute(statement)


def downgrade() -> None:
    allowed = ", ".join(f"'{t}'" for t in TYPES_BEFORE_0743)
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "DROP CONSTRAINT IF EXISTS ck_b2b_contract_documents_type"
    )
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "ADD CONSTRAINT ck_b2b_contract_documents_type "
        f"CHECK (document_type IN ({allowed})) NOT VALID"
    )
