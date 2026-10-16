"""„Ludzie w NEXUSIE” — Sprawy administracja@.

Revision ID: 0459_admin_cases
Revises: 0458_contract_care

Zakres: sprawy, wiadomości, komentarze, stan czytnika skrzynki. SQL ma jedno źródło (``app/services/admin_cases_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import admin_cases_schema as schema

revision = "0459_admin_cases"
down_revision = "0458_contract_care"
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
