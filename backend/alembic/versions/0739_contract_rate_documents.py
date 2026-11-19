"""Stawki z dokumentów kontraktu (B, decyzja Artura 18.11.2026).

Revision ID: 0739_contract_rate_documents
Revises: 0737_board_reports

Tabela ``contract_document_rate_reads`` (odczyt stawki Partnera z każdego pliku
umowy i aneksu w Dokumentach kontraktu, różnica z harmonogramem i decyzja) oraz
funkcja AI ``contract_document_rate_read``. DDL ma jedno źródło
(``app/services/contract_rate_documents/schema_sql.py``); entrypoint wykonuje je
przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services.contract_rate_documents import schema_sql as schema

revision = "0739_contract_rate_documents"
down_revision = "0737_board_reports"
branch_labels = None
depends_on = None

_AI_KEY = "contract_document_rate_read"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_AI_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_AI_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_AI_KEY}')"
    )
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE).
def downgrade() -> None:
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_AI_KEY}'")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
