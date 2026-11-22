"""Układ CV: klasyczny Word albo „Nowe CV” w PDF — przy CV etapu, wersji,
wygenerowanym dokumencie i regule klienta, plus dodatki strony 1.

Revision ID: 0753_cv_layout
Revises: 0752_drop_compass_workdays_sync_state

SQL i powody: ``app/services/cv_layout_schema.py`` (to samo źródło czyta
``entrypoint.sh``).
"""

from alembic import op

from app.services import cv_layout_schema as schema

revision = "0753_cv_layout"
down_revision = "0752_drop_compass_workdays_sync_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table, column, _ddl in schema.ADDED_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
