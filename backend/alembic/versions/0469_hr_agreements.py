"""„Ludzie w NEXUSIE” — umowy z ludźmi (etap 5, E5).

Revision ID: 0469_hr_agreements
Revises: 0468_hr_documents

SQL ma jedno źródło (``app/services/hr_agreements_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_agreements_schema as schema

revision = "0469_hr_agreements"
down_revision = "0468_hr_documents"
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
