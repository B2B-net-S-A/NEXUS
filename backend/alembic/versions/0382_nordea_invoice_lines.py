"""Nordea: pozycja faktury cyklicznej zapisana przy zamówieniu (25.09.2026).

Revision ID: 0382_nordea_invoice_lines
Revises: 0381_job_boards_jjit_rocketjobs

``client_orders.invoice_lines`` (JSONB, NULL) trzyma formułę pozycji faktury
Nordei („NIDS: …, IT Retail Banking, Nordea Contact: …, Contractor: … ID:")
odczytaną z Call Off Agreement, razem z ręczną poprawką Finansów. Wypełnia ją
wgranie PDF-a, a zamówienia sprzed wdrożenia — pętla ``order_gaps``
(``nordea_invoice_lines.fill_missing``). Lustro DDL w ``entrypoint.sh`` (prod
alembic bywa osierocony) — pilnuje ``test_nordea_invoice_lines.py``.
"""

from alembic import op

revision = "0382_nordea_invoice_lines"
down_revision = "0381_job_boards_jjit_rocketjobs"
branch_labels = None
depends_on = None

ADD_COLUMN = (
    "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS invoice_lines JSONB NULL"
)


def upgrade() -> None:
    op.execute(ADD_COLUMN)


def downgrade() -> None:
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS invoice_lines")
