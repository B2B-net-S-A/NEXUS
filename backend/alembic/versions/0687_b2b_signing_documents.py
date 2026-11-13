"""Paczka do podpisu: umowa B2B i dokumenty do startu pod jednym linkiem.

Revision ID: 0687_b2b_signing_documents
Revises: 0686_autofill_gaps_round4

Decyzja Artura 13.11.2026: kontraktor podpisuje za jednym razem umowę, NDA,
oświadczenie o niekaralności i każdy wzór z listy klienta „Dokumenty do
startu”. DDL w ``app/services/b2b_esign/documents_schema.py``, lustro
w ``entrypoint.sh``.
"""

from alembic import op

from app.services.b2b_esign.documents_schema import TABLE_DDL

revision = "0687_b2b_signing_documents"
down_revision = "0686_autofill_gaps_round4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS b2b_signing_documents")
