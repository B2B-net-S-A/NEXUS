"""Back office na sprawach: karty, historia kart i skład zespołów.

Revision ID: 0629_back_office
Revises: 0628_sales_meeting_transcripts

SQL i powody: ``app/services/back_office_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import back_office_schema as schema

revision = "0629_back_office"
down_revision = "0628_sales_meeting_transcripts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
