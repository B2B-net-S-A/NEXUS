"""Import rejestru umów z Excela działu (powtarzalny)

Revision ID: 0359_b2b_register_import
Revises: 0358_b2b_contract_documents
Create Date: 2026-09-23 20:00:00.000000

Kolumny ``source``/``source_key``/``raw_contract_number``/… na
``b2b_generated_contracts``, ``seq`` i ``year`` NULL-owalne, UNIQUE(year, seq)
częściowy, tabele przebiegów importu. DDL w
``app/services/b2b_register_import/schema_sql.py`` — to samo źródło czyta
siatka bezpieczeństwa w ``entrypoint.sh``.

Downgrade zdejmuje wiersze z Excela, kolumny i tabele i przywraca pełny
UNIQUE(year, seq) oraz NOT NULL.
"""

from alembic import op

from app.services.b2b_register_import.schema_sql import TABLE_DDL

revision = "0359_b2b_register_import"
down_revision = "0358_b2b_contract_documents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DELETE FROM b2b_generated_contracts WHERE source = 'excel'")
    op.execute("DROP INDEX IF EXISTS ux_b2b_generated_contracts_excel_source_key")
    op.execute("DROP INDEX IF EXISTS ix_b2b_generated_contracts_source")
    op.execute("DROP INDEX IF EXISTS uq_b2b_generated_contracts_year_seq")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_b2b_generated_contracts_year_seq "
        "ON b2b_generated_contracts (year, seq)"
    )
    for column in (
        "excel_missing_since",
        "import_run_id",
        "business_data_annex_done_at",
        "needs_business_data_annex",
        "legacy_data",
        "recruiter_user_id",
        "position",
        "start_date_mode",
        "contract_kind",
        "raw_contract_number",
        "source_key",
        "source",
    ):
        op.execute(
            f"ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS {column}"
        )
    op.execute("ALTER TABLE b2b_generated_contracts ALTER COLUMN seq SET NOT NULL")
    op.execute("ALTER TABLE b2b_generated_contracts ALTER COLUMN year SET NOT NULL")
    op.execute("DROP TABLE IF EXISTS b2b_register_import_rows")
    op.execute("DROP TABLE IF EXISTS b2b_register_import_runs")
