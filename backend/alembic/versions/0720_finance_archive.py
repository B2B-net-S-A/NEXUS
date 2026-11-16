"""Archiwum dokumentów z eBI24 w Finansach (E5).

Revision ID: 0720_finance_archive
Revises: 0719_payroll_salaries

Tabela ``finance_archive_documents`` — metadane ok. 50 tys. dokumentów z
archiwum eBI24; pliki leżą na dysku (``UPLOADS_DIR/ebi24_archive``). DDL ma
jedno źródło (``app/services/finance_archive_schema.py``); entrypoint wykonuje
je przy każdym starcie przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import finance_archive_schema as schema

revision = "0720_finance_archive"
down_revision = "0719_payroll_salaries"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
