"""Format pliku CV klienta: ``client_cv_rules.cv_file_format`` (Word / PDF / oba).

Revision ID: 0777_client_cv_file_format
Revises: 0776_settlement_extra_source_rcp

Decyzja Artura z 25.11.2026: reguła CV klienta mówi, w jakim pliku klient chce
CV, a główny przycisk pobrania idzie za nią. NULL = bez wymagań (jak dotąd).
SQL: ``app/services/cv_layout_schema.py`` (``FILE_FORMAT_DDL``; to samo źródło
czyta ``entrypoint.sh``).
"""

from alembic import op

from app.services import cv_layout_schema as schema

revision = "0777_client_cv_file_format"
down_revision = "0776_settlement_extra_source_rcp"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.FILE_FORMAT_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for table, column, _ddl in schema.FILE_FORMAT_COLUMNS:
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
