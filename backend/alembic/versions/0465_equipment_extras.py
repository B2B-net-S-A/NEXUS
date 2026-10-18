"""„Ludzie w NEXUSIE” — Sprzęt, etapy 4–5: Intune i edycje Akademii.

Revision ID: 0465_equipment_extras
Revises: 0464_equipment

Zakres: migawka urządzeń z Intune, stan pętli, lista edycji Akademii, hotel i bilet uczestnika, uczestnik Akademii jako czwarty posiadacz sprzętu. SQL ma jedno źródło (``app/services/equipment_extras_schema.py``) — ten sam
moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import equipment_extras_schema as schema

revision = "0465_equipment_extras"
down_revision = "0464_equipment"
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
