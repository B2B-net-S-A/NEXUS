"""Panel konsultanta: aktywacja, materiały na start, szablon rozliczenia, trenerzy.

Revision ID: 0646_consultant_panel
Revises: 0645_back_office_role

SQL i powody: ``app/services/consultant_panel_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import consultant_panel_schema as schema

revision = "0646_consultant_panel"
down_revision = "0645_back_office_role"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
