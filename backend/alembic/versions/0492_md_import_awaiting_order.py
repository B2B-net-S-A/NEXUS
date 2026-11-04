"""Import MD: wiersz bez numeru zamówienia czeka na kolejne zamówienie (21.10.2026).

Revision ID: 0492_md_import_awaiting_order
Revises: 0491_approval_contract_basis

Osoba z dwoma wierszami w arkuszu — jeden z numerem zamówienia, drugi bez
(zamówienie jeszcze nie wpłynęło) — nie jest już sumowana na zamówienie
z numerem. Wiersz bez numeru dostaje status ``awaiting_order`` („Oczekuje na
zamówienie”), ``awaiting_origin_order_id`` wskazuje linię zamówienia
z numerem (tam wisi „Pozostało do zafakturowania”), a ``md_pending`` mówi, ile
MD jeszcze czeka. Status ``superseded`` dostaje taki wiersz starszej paczki,
gdy nowsza paczka za ten sam miesiąc przyniosła własny.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_md_import_awaiting_order_mirror.py``.
"""

from alembic import op

revision = "0492_md_import_awaiting_order"
down_revision = "0491_approval_contract_basis"
branch_labels = None
depends_on = None

ADD_ORIGIN = (
    "ALTER TABLE md_consumption_import_rows "
    "ADD COLUMN IF NOT EXISTS awaiting_origin_order_id INTEGER NULL "
    "REFERENCES client_orders (id) ON DELETE SET NULL"
)
ADD_PENDING = (
    "ALTER TABLE md_consumption_import_rows "
    "ADD COLUMN IF NOT EXISTS md_pending NUMERIC(16, 6) NULL"
)
ADD_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_md_import_rows_awaiting_origin "
    "ON md_consumption_import_rows (awaiting_origin_order_id) "
    "WHERE awaiting_origin_order_id IS NOT NULL"
)
STATUSES = (
    "'applied', 'needs_assignment', 'unmatched', 'cost_only', 'overflow', "
    "'awaiting_order', 'superseded'"
)


def upgrade() -> None:
    op.execute(ADD_ORIGIN)
    op.execute(ADD_PENDING)
    op.execute(ADD_INDEX)
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "ADD CONSTRAINT ck_md_import_rows_status "
        f"CHECK (status IN ({STATUSES})) NOT VALID"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE md_consumption_import_rows SET status = 'unmatched' "
        "WHERE status IN ('awaiting_order', 'superseded')"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "ADD CONSTRAINT ck_md_import_rows_status CHECK (status IN "
        "('applied', 'needs_assignment', 'unmatched', 'cost_only', 'overflow')) "
        "NOT VALID"
    )
    op.execute("DROP INDEX IF EXISTS ix_md_import_rows_awaiting_origin")
    op.execute(
        "ALTER TABLE md_consumption_import_rows DROP COLUMN IF EXISTS md_pending"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP COLUMN IF EXISTS awaiting_origin_order_id"
    )
