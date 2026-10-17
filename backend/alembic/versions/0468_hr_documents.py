"""„Ludzie w NEXUSIE” — dokumenty osoby (e-teczka, etap 5, E4).

Revision ID: 0468_hr_documents
Revises: 0467_hr_settlements

SQL ma jedno źródło (``app/services/hr_documents_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_documents_schema as schema

revision = "0468_hr_documents"
down_revision = "0467_hr_settlements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
