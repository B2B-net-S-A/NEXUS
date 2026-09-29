"""Generator aneksów: stawki z ostatniego aneksu w wierszu rejestru umów B2B.

Revision ID: 0398_b2b_annex_rates
Revises: 0397_skill_catalog_tools

``b2b_generated_contracts.annex_rates`` (JSONB) — wiersz „Umów bieżących”
dostaje stawki z aneksu zmiany stawki już przy jego wygenerowaniu (ticket
„Generator aneksów”, decyzja Artura 29.09.2026). DDL ma jedno źródło z siatką
w ``entrypoint.sh`` (``services/b2b_documents/schema_sql.py``).
"""

from alembic import op

from app.services.b2b_documents.schema_sql import ANNEX_GENERATOR_DDL

revision = "0398_b2b_annex_rates"
down_revision = "0397_skill_catalog_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in ANNEX_GENERATOR_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS annex_rates")
