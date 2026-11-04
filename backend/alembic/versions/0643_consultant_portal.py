"""Portal konsultanta: linki, sesje, kody SMS, FAQ, rozmowy, oceny, dokumenty.

Revision ID: 0643_consultant_portal
Revises: 0642_back_office

SQL i powody: ``app/services/consultant_portal_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import consultant_portal_schema as schema

revision = "0643_consultant_portal"
down_revision = "0642_back_office"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
