"""Umowy wykonawcze Centrum e-Zdrowia — dwupoziomowa struktura umów.

Revision ID: 0312_ezdrowie_executive_contracts
Revises: 0311_oauth_client_acting_user
Create Date: 2026-09-16

Do tej pory konsultant u klienta 115 był tagowany po „części umowy ramowej"
(``client_orders.project_part``). Ticket 09.2026: część ramowa → 0..N umów
wykonawczych, konsultant przypisany do KONKRETNEJ umowy wykonawczej.

* ``client_framework_contracts.project_part`` — umowa ramowa JEST częścią
  (słownik ``cz1|cz2|cz4|cz5|cz6``, jedna ramowa na część u klienta).
* ``client_executive_contracts`` — numer + FK do ramowej + status
  (``active`` domyślnie — ticket), unikalny numer per klient.
* ``client_orders.executive_contract_id`` i ``client_order_groups.executive_contract_id``
  — przypisanie zamówienia/karty MD; ``project_part`` zostaje jako wartość
  pochodna z części umowy ramowej.
* zasiew docelowej struktury (5 umów ramowych, 3 wykonawcze) — jedno źródło
  SQL w ``app/services/ezdrowie_structure.py``; no-op bez klienta 115.

Numery „DO UMOWY RAMOWEJ" na dokumentach są błędne — struktura nie jest
parsowana z treści. Additive; mirrored in ``entrypoint.sh``.
"""

from alembic import op

from app.services.ezdrowie_structure import EZDROWIE_STRUCTURE_SEED_SQL

revision = "0312_ezdrowie_executive_contracts"
down_revision = "0311_oauth_client_acting_user"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE client_framework_contracts "
        "ADD COLUMN IF NOT EXISTS project_part VARCHAR(8) NULL"
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE client_framework_contracts
                ADD CONSTRAINT ck_client_framework_contracts_project_part
                CHECK (
                    project_part IS NULL
                    OR project_part IN ('cz1', 'cz2', 'cz4', 'cz5', 'cz6')
                );
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ux_client_framework_contracts_client_part "
        "ON client_framework_contracts (client_id, project_part) "
        "WHERE project_part IS NOT NULL"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS client_executive_contracts (
            id SERIAL PRIMARY KEY,
            client_id INTEGER NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
            framework_contract_id INTEGER NOT NULL
                REFERENCES client_framework_contracts (id) ON DELETE RESTRICT,
            number VARCHAR(64) NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'active',
            notes TEXT NULL,
            created_by_user_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_client_executive_contracts_status
                CHECK (status IN ('active', 'ended')),
            CONSTRAINT ck_client_executive_contracts_number_nonempty
                CHECK (char_length(btrim(number)) > 0),
            CONSTRAINT ux_client_executive_contracts_client_number
                UNIQUE (client_id, number)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_executive_contracts_client_id "
        "ON client_executive_contracts (client_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_executive_contracts_framework "
        "ON client_executive_contracts (framework_contract_id)"
    )
    op.execute(
        "ALTER TABLE client_orders ADD COLUMN IF NOT EXISTS executive_contract_id "
        "INTEGER NULL REFERENCES client_executive_contracts (id) ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_orders_executive_contract_id "
        "ON client_orders (executive_contract_id)"
    )
    op.execute(
        "ALTER TABLE client_order_groups ADD COLUMN IF NOT EXISTS executive_contract_id "
        "INTEGER NULL REFERENCES client_executive_contracts (id) ON DELETE RESTRICT"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_client_order_groups_executive_contract_id "
        "ON client_order_groups (executive_contract_id)"
    )
    op.execute(EZDROWIE_STRUCTURE_SEED_SQL)


def downgrade() -> None:
    op.execute("ALTER TABLE client_order_groups DROP COLUMN IF EXISTS executive_contract_id")
    op.execute("ALTER TABLE client_orders DROP COLUMN IF EXISTS executive_contract_id")
    op.execute("DROP TABLE IF EXISTS client_executive_contracts")
    op.execute("DROP INDEX IF EXISTS ux_client_framework_contracts_client_part")
    op.execute(
        "ALTER TABLE client_framework_contracts "
        "DROP CONSTRAINT IF EXISTS ck_client_framework_contracts_project_part"
    )
    op.execute("ALTER TABLE client_framework_contracts DROP COLUMN IF EXISTS project_part")
