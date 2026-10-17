"""„Ludzie w NEXUSIE” — Opieka nad konsultantami i technologie.

Revision ID: 0462_contract_care
Revises: 0461_hr_lifecycle

Zakres: opiekun kontraktu, plan kontaktów, rozmowy, karty technologiczne, kolejka „Do przepięcia”. SQL ma jedno źródło (``app/services/contract_care_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import contract_care_schema as schema

revision = "0462_contract_care"
down_revision = "0461_hr_lifecycle"
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
