"""Dokumenty pochodne umowy B2B (aneksy, rozwiązania, umowa przedwstępna)

Revision ID: 0362_b2b_contract_documents
Revises: 0361_cv_qc
Create Date: 2026-09-23 18:00:00.000000

Tabela ``b2b_contract_documents``, cztery nowe typy aneksu w
``contractamendmenttype`` i kolumna ``b2b_generated_contracts.template_version``.
DDL w ``app/services/b2b_documents/schema_sql.py`` — to samo źródło czyta
siatka bezpieczeństwa w ``entrypoint.sh``.

Downgrade zdejmuje tabelę i kolumnę; wartości enuma zostają (Postgres nie ma
``DROP VALUE``, a aneksy mogą już na nie wskazywać).
"""

from alembic import op

from app.services.b2b_documents.schema_sql import BACKFILL_DDL, ENUM_DDL, TABLE_DDL

revision = "0362_b2b_contract_documents"
down_revision = "0361_cv_qc"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in ENUM_DDL:
            op.execute(statement)
    for statement in TABLE_DDL:
        op.execute(statement)
    for statement in BACKFILL_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS b2b_contract_documents")
    op.execute(
        "ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS template_version"
    )
