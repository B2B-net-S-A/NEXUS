"""Kwota faktury z groszami — ``invoices.amount`` INTEGER → NUMERIC(14,2).

Revision ID: 0391_money_invoice_amount_grosze
Revises: 0390_cand_retained_candidate_files

Runda 10 audytu (R10-X1-1): faktura przyjmowała wyłącznie pełne złote —
formularz blokował „12345,67”, a API odpowiadało 422 na kwotę z groszami, więc
suma należności i zapłat (DSO, „z dokładnością do grosza”) odjeżdżała od
faktur. Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony); ALTER idzie
tylko przy różnicy typu, więc kolejne starty nie biorą zamka tabeli.
"""

from alembic import op

revision = "0391_money_invoice_amount_grosze"
down_revision = "0390_cand_retained_candidate_files"
branch_labels = None
depends_on = None

# Jedno źródło dla migracji i lustra w ``entrypoint.sh`` (tekst identyczny —
# pilnuje ``tests/test_audit_r10_money.py``).
WIDEN_INVOICE_AMOUNT = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns c
        WHERE c.table_schema = current_schema()
          AND c.table_name = 'invoices'
          AND c.column_name = 'amount'
          AND (c.data_type <> 'numeric'
               OR c.numeric_precision IS DISTINCT FROM 14
               OR c.numeric_scale IS DISTINCT FROM 2)
    ) THEN
        ALTER TABLE invoices
            ALTER COLUMN amount TYPE NUMERIC(14, 2) USING amount::numeric(14, 2);
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(WIDEN_INVOICE_AMOUNT)


def downgrade() -> None:
    # Zaokrąglenie do pełnych złotych gubi grosze — świadome przy cofnięciu.
    op.execute(
        "ALTER TABLE invoices ALTER COLUMN amount TYPE INTEGER "
        "USING round(amount)::integer"
    )
