"""Zamówienia MD: zakres opcjonalny linii + status rozliczenia miesiąca.

Revision ID: 0313_md_optional_scope_and_consumption_status
Revises: 0312_ezdrowie_executive_contracts
Create Date: 2026-09-16

Faza B ticketu Centrum e-Zdrowia (09.2026):

* ``client_orders.md_optional_total`` — zakres OPCJONALNY w MD obok zakresu
  podstawowego (``md_total``). Zużycie wypełnia najpierw podstawę, nadwyżka
  schodzi z opcji; ``md_remaining`` liczy całość, więc alerty i wyczerpanie
  widzą oba zakresy. NULL = „brak opcji w umowie".
* ``client_order_md_consumptions.status`` (``accepted`` = „Zaakceptowany",
  ``protocol`` = „Protokół", NULL = z importu bez statusu) i ``note`` —
  ręczne wpisy miesięczne per osoba („Rozliczenia miesięczne").

Additive; mirrored in ``entrypoint.sh``.
"""

from alembic import op

revision = "0313_md_optional_scope_and_consumption_status"
down_revision = "0312_ezdrowie_executive_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_orders "
        "ADD COLUMN IF NOT EXISTS md_optional_total NUMERIC(16, 6) NULL"
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_orders
                ADD CONSTRAINT ck_client_orders_md_optional
                CHECK (
                    md_optional_total IS NULL
                    OR (md_optional_total >= 0 AND md_total IS NOT NULL)
                );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        "ALTER TABLE client_order_md_consumptions "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(16) NULL"
    )
    op.execute(
        "ALTER TABLE client_order_md_consumptions "
        "ADD COLUMN IF NOT EXISTS note VARCHAR(255) NULL"
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_order_md_consumptions
                ADD CONSTRAINT ck_md_consumptions_status
                CHECK (status IS NULL OR status IN ('accepted', 'protocol'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_order_md_consumptions "
        "DROP CONSTRAINT IF EXISTS ck_md_consumptions_status"
    )
    op.execute("ALTER TABLE client_order_md_consumptions DROP COLUMN IF EXISTS note")
    op.execute("ALTER TABLE client_order_md_consumptions DROP COLUMN IF EXISTS status")
    op.execute(
        "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS ck_client_orders_md_optional"
    )
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS md_optional_total")
