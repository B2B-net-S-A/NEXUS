"""„Ludzie w NEXUSIE” — komunikaty do konsultantów (O12).

Revision ID: 0465_care_announcements
Revises: 0464_equipment_extras

Zakres: komunikaty, zamrożona lista odbiorców z wykluczeniami i stanem
wysyłki, wypisy z komunikatów informacyjnych, odpowiedzi i odbite maile jako
sprawy administracja@. SQL ma jedno źródło (``app/services/care_announcements_schema.py``)
— ten sam moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import care_announcements_schema as schema

revision = "0465_care_announcements"
down_revision = "0464_equipment_extras"
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
