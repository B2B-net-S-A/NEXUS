"""Import MD: wiersz przekraczający pulę czeka na zatwierdzenie (ticket 1.1, 24.09.2026).

Revision ID: 0375_md_import_row_overflow
Revises: 0374_trainee_call_lists

Zaksięgowanie wiersza, po którym saldo osoby (pula per osoba) albo zamówienia
(pula wspólna) zeszłoby poniżej zera, nie dzieje się już automatycznie. Wiersz
dostaje status ``overflow`` („Do weryfikacji – przekroczenie puli o X MD”),
a ``overflow_md`` zapamiętuje X z chwili importu. Zatwierdzenie księguje go
ręcznie z wpisem w historii zamówienia.

Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) — pilnuje
``test_md_import_row_overflow_mirror.py``.
"""

from alembic import op

revision = "0375_md_import_row_overflow"
down_revision = "0374_trainee_call_lists"
branch_labels = None
depends_on = None

ADD_OVERFLOW_MD = (
    "ALTER TABLE md_consumption_import_rows "
    "ADD COLUMN IF NOT EXISTS overflow_md NUMERIC(16, 6) NULL"
)
STATUSES = "'applied', 'needs_assignment', 'unmatched', 'cost_only', 'overflow'"


def upgrade() -> None:
    op.execute(ADD_OVERFLOW_MD)
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
        "UPDATE md_consumption_import_rows SET status = 'needs_assignment' "
        "WHERE status = 'overflow'"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "DROP CONSTRAINT IF EXISTS ck_md_import_rows_status"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows "
        "ADD CONSTRAINT ck_md_import_rows_status CHECK (status IN "
        "('applied', 'needs_assignment', 'unmatched', 'cost_only')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE md_consumption_import_rows DROP COLUMN IF EXISTS overflow_md"
    )
