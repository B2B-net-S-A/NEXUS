"""„Ludzie w NEXUSIE” — Urlopy i zastępstwa.

Revision ID: 0455_hr_leave
Revises: 0454_hr_notifications

Zakres: wnioski urlopowe (dzień per wiersz), akceptacje, zastępstwa, kolejka operacji Microsoft 365, stan skrzynek. SQL ma jedno źródło (``app/services/hr_leave_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_leave_schema as schema

revision = "0455_hr_leave"
down_revision = "0454_hr_notifications"
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
