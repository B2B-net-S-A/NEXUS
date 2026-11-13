"""Szkolenia w Teams: spotkanie z NEXUSA, zaproszenia, nagranie, transkrypt, oceny.

Revision ID: 0696_training_teams
Revises: 0695_finance_ledger

SQL i powody: ``app/services/trainings_schema.py`` (``TEAMS_DDL``; to samo źródło
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``).
"""

from alembic import op

from app.services import trainings_schema as schema

revision = "0696_training_teams"
down_revision = "0695_finance_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.TEAMS_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table in reversed(schema.TEAMS_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP INDEX IF EXISTS ix_trainings_recording_due")
    for table, columns in schema.TEAMS_COLUMNS.items():
        for column in columns:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
