"""„Ludzie w NEXUSIE” — Płace i premie.

Revision ID: 0460_hr_payroll
Revises: 0459_hr_time

Zakres: historia stawek, premie, okresy płacowe i zamrożone linie. SQL ma jedno źródło (``app/services/hr_payroll_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_payroll_schema as schema

revision = "0460_hr_payroll"
down_revision = "0459_hr_time"
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
