"""„Ludzie w NEXUSIE” — Mój miesiąc.

Revision ID: 0459_hr_time
Revises: 0458_hr_leave

Zakres: obecność (tylko wyjątki), timesheety i wpisy, szablony opisów. SQL ma jedno źródło (``app/services/hr_time_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_time_schema as schema

revision = "0459_hr_time"
down_revision = "0458_hr_leave"
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
