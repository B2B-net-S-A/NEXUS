"""Runda 10 audytu (MD): dwa nowe wyniki kosztowe wiersza importu MD.

Revision ID: 0391_md_import_cost_statuses
Revises: 0390_cand_retained_candidate_files

``md_consumption_import_rows.cost_status``:

* ``invoice_unreadable`` (R10-N5-5) — niepustej kwoty w „Fakturze” nie dało
  się odczytać. Wiersz z poprawną liczbą MD zostaje w imporcie (do 27.09 szedł
  do pominiętych razem z MD), a faktura czeka na ręczne rozliczenie.
* ``order_exhausted`` (R10-N5-6) — numer z „Uwag” wskazuje wyczerpane
  zamówienie kosztowe tej osoby; faktura nie została rozliczona (dotąd opis
  „brak zamówienia o tym numerze”).

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0393_md_import_cost_statuses"
down_revision = "0392_fin_order_gap_episodes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_cost_status CHECK (cost_status IS NULL OR cost_status IN "
        "('applied', 'unmatched_number', 'unmatched_consultant', "
        "'non_positive_amount', 'invoice_unreadable', 'order_exhausted')) NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE md_consumption_import_rows SET cost_status = 'unmatched_number' "
        "WHERE cost_status IN ('invoice_unreadable', 'order_exhausted')"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_cost_status CHECK (cost_status IS NULL OR cost_status IN "
        "('applied', 'unmatched_number', 'unmatched_consultant', "
        "'non_positive_amount')) NOT VALID"
    )
