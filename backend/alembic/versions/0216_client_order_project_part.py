"""client_orders.project_part — „część umowy" Centrum e-Zdrowia (ticket #3).

Revision ID: 0216_client_order_project_part
Revises: 0215_client_portfolio_scope_overrides
Create Date: 2026-08-06

Nullable VARCHAR(8) + CHECK na słownik ``cz1|cz2|cz4|cz5|cz6`` (cz.3 celowo
nie istnieje). Kolumna MUSI być nullable: auto-draft z podpisanej umowy B2B
i zamówienia wszystkich innych klientów powstają bez części — „wymagane"
egzekwuje wyłącznie walidacja API/UI dla client_id=115 (bramka po id,
decyzja Fazy B). VARCHAR+CHECK zamiast enuma PG — prostszy mirror w
entrypoint.sh (prod alembic orphaned).

Additive and reversible. Mirrored in ``entrypoint.sh``.
"""

from alembic import op


revision = "0216_client_order_project_part"
down_revision = "0215_client_portfolio_scope_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE client_orders
            ADD COLUMN IF NOT EXISTS project_part VARCHAR(8) NULL
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_orders
                ADD CONSTRAINT ck_client_orders_project_part
                CHECK (
                    project_part IS NULL
                    OR project_part IN ('cz1', 'cz2', 'cz4', 'cz5', 'cz6')
                );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE client_orders DROP CONSTRAINT IF EXISTS ck_client_orders_project_part"
    )
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS project_part")
