"""Zakładka „Zużycie” przy zamówieniu kosztowym — ręczny wpis kwoty za miesiąc.

Revision ID: 0493_cost_consumption_manual_entry
Revises: 0492_md_import_awaiting_order

* ``client_order_invoice_consumptions.status`` / ``note`` — lustro pól
  ``client_order_md_consumptions`` (0313): formularz „Nowy wpis miesięczny”
  przy zamówieniu kosztowym ma te same pola co przy MD.
* ``md_consumption_import_rows.cost_status`` dostaje ``manual_kept``: import
  Finansów nie nadpisuje ręcznego wpisu kosztowego za ten sam miesiąc (decyzja
  Artura 21.10.2026), wiersz arkusza zostaje z tym statusem do decyzji.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0493_cost_consumption_manual_entry"
down_revision = "0492_md_import_awaiting_order"
branch_labels = None
depends_on = None

_COST_STATUSES = (
    "'applied', 'unmatched_number', 'unmatched_consultant', "
    "'non_positive_amount', 'invoice_unreadable', 'order_exhausted'"
)


def _cost_status_check(values: str) -> None:
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_cost_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows ADD CONSTRAINT "
        "ck_md_import_rows_cost_status CHECK (cost_status IS NULL OR cost_status IN "
        f"({values})) NOT VALID"
    )


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(16) NULL"
    )
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions "
        "ADD COLUMN IF NOT EXISTS note VARCHAR(255) NULL"
    )
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions "
        "DROP CONSTRAINT IF EXISTS ck_invoice_consumptions_status"
    )
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions ADD CONSTRAINT "
        "ck_invoice_consumptions_status "
        "CHECK (status IS NULL OR status IN ('accepted', 'protocol'))"
    )
    _cost_status_check(_COST_STATUSES + ", 'manual_kept'")


def downgrade() -> None:
    op.execute(
        "UPDATE md_consumption_import_rows SET cost_status = 'unmatched_number' "
        "WHERE cost_status = 'manual_kept'"
    )
    _cost_status_check(_COST_STATUSES)
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions "
        "DROP CONSTRAINT IF EXISTS ck_invoice_consumptions_status"
    )
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions DROP COLUMN IF EXISTS note"
    )
    op.execute(
        "ALTER TABLE client_order_invoice_consumptions DROP COLUMN IF EXISTS status"
    )
