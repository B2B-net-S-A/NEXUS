"""Wzory własne Generatora Umów B2B (asystent prawny, część B, 25.11.2026).

Revision ID: 0786_custom_document_templates
Revises: 0785_legal_corpus

Tabele ``custom_document_templates`` i ``custom_document_template_versions``
(wzór, wersje z DOCX i listą pól, zatwierdzanie przez administratora), typ
dokumentu ``custom_template`` w CHECK ``ck_b2b_contract_documents_type`` i
funkcja AI ``legal_template_draft``. DDL ma jedno źródło z lustrem w
``entrypoint.sh``: ``app/services/custom_templates/schema.py`` (przez
``hr_schema_bundle``) i ``app/services/b2b_documents/schema_sql.py``. Same
dodania: stary kod działa na nowym schemacie.

``down_revision`` wskazuje 0778 jak każda część asystenta prawnego — sesja
główna łańcuchuje 0785–0791 przy scalaniu (``docs/asystent-prawny-plan.md``).
"""

from alembic import op

from app.services.b2b_documents.schema_sql import (
    TYPE_CHECK_DDL,
    TYPES_BEFORE_CUSTOM_TEMPLATES,
)
from app.services.custom_templates import schema

revision = "0786_custom_document_templates"
down_revision = "0785_legal_corpus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(schema.AI_ENUM_DDL)
    op.execute(schema.AI_SEED_DDL)
    for stmt in schema.ALL_DDL:
        op.execute(stmt)
    for stmt in TYPE_CHECK_DDL:
        op.execute(stmt)


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE). Dokumenty
# wydane ze wzorów własnych zostają w rejestrze: CHECK wraca jako NOT VALID.
def downgrade() -> None:
    allowed = ", ".join(f"'{t}'" for t in TYPES_BEFORE_CUSTOM_TEMPLATES)
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "DROP CONSTRAINT IF EXISTS ck_b2b_contract_documents_type"
    )
    op.execute(
        "ALTER TABLE b2b_contract_documents "
        "ADD CONSTRAINT ck_b2b_contract_documents_type "
        f"CHECK (document_type IN ({allowed})) NOT VALID"
    )
    op.execute(f"DELETE FROM ai_features WHERE feature = '{schema.AI_FEATURE}'")
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
