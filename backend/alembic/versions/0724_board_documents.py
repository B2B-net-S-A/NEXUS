"""Dokumenty Rady nadzorczej i odpisy KRS spółki (R1).

Revision ID: 0724_board_documents
Revises: 0723_b2b_annex_custom

Tabele ``board_documents`` (rejestr dokumentów korporacyjnych) i
``board_krs_snapshots`` (odpis pełny KRS co noc), wartość powiadomienia
``board_krs_entry`` i funkcja AI ``board_document_read`` (odczyt skanu uchwały
albo protokołu jako propozycja). DDL tabel ma jedno źródło
(``app/services/board_documents_schema.py``); entrypoint wykonuje je przy
każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import board_documents_schema as schema

revision = "0724_board_documents"
down_revision = "0723_b2b_annex_custom"
branch_labels = None
depends_on = None

_AI_KEY = "board_document_read"
_NOTIFICATION_TYPE = "board_krs_entry"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_AI_KEY}'")
        op.execute(
            f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{_NOTIFICATION_TYPE}'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_AI_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_AI_KEY}')"
    )
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


# Wartości enumów zostają po downgrade (Postgres nie ma DROP VALUE).
def downgrade() -> None:
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_AI_KEY}'")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
