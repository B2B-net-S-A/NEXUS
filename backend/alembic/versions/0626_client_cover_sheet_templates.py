"""Karta przed CV: wzór Worda klienta w bazie (Credit Agricole, 29.10.2026).

Revision ID: 0626_client_cover_sheet_templates
Revises: 0625_novelty_progress

Credit Agricole wymaga z każdym CV jednostronicowej karty dostawcy. Wzór
wgrywa Delivery Lead w edytorze reguły CV klienta; wiersz = karta włączona.
SQL i powód: ``app/services/cover_sheet_schema.py``. Lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import cover_sheet_schema as schema

revision = "0626_client_cover_sheet_templates"
down_revision = "0625_novelty_progress"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in schema.ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    for statement in schema.DOWNGRADE_DDL:
        op.execute(statement)
