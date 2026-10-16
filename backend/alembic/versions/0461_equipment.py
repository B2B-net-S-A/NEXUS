"""„Ludzie w NEXUSIE” — Sprzęt i protokoły.

Revision ID: 0461_equipment
Revises: 0460_admin_cases

Zakres: modele i egzemplarze, osoby zewnętrzne, wydania, protokoły z linkiem do podpisu, zadania, import plików recepcji. SQL ma jedno źródło (``app/services/equipment_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import equipment_schema as schema

revision = "0461_equipment"
down_revision = "0460_admin_cases"
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
