"""Szkolenia i trenerzy: zamówienie, wycena A–E, umowa szkoleniowa, pliki, biblioteka.

Revision ID: 0694_trainings
Revises: 0693_user_appearance_prefs

SQL i powody: ``app/services/trainings_schema.py`` (to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import trainings_schema as schema

revision = "0694_trainings"
down_revision = "0693_user_appearance_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for column in schema.APPLICATION_COLUMNS:
        op.execute(
            f"ALTER TABLE cp_trainer_applications DROP COLUMN IF EXISTS {column}"
        )
