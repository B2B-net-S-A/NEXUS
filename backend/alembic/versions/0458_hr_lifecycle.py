"""„Ludzie w NEXUSIE” — Wejście i odejście.

Revision ID: 0458_hr_lifecycle
Revises: 0457_hr_payroll

Zakres: szablony i sprawy cyklu życia, zadania, przekazania pracy. SQL ma jedno źródło (``app/services/hr_lifecycle_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_lifecycle_schema as schema

revision = "0458_hr_lifecycle"
down_revision = "0457_hr_payroll"
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
