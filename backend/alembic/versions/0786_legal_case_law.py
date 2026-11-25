"""Orzecznictwo dla asystenta prawnego: tabela ``legal_cases`` (część C).

Revision ID: 0786_legal_case_law
Revises: 0785_custom_document_templates

SQL i powody: ``app/services/legal_case_law/schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``). Reguła:
``docs/claude/asystent-prawny/orzecznictwo-i-interpretacje.md``.
``down_revision`` łańcuchuje sesja scalająca części asystenta prawnego.
"""

from alembic import op

from app.services.legal_case_law import schema

revision = "0786_legal_case_law"
down_revision = "0785_custom_document_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
