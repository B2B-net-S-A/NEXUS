"""Szczegóły administracyjne umowy: replacement i wymiar FTE.

Revision ID: 0524_agreement_admin_details
Revises: 0522_candidate_client_forms

Decyzje Artura z 26.10.2026 (kafelek „Szczegóły administracyjne” w Generatorze):

* ``is_replacement`` / ``replaced_contract_id`` — umowa zastępuje kontraktora
  (kontrakt osoby zastąpionej); ``fte`` — 1 / 0,75 / 0,5 / 0,25. Te same kolumny
  w wierszu umowy (wpisuje Generator) i w kontrakcie (kopia przy podpisie,
  fill-only — późniejsza zmiana w kontrakcie wygrywa).
* Rekruter i Delivery Lead NIE są kolumnami: to odbiorcy premii z reguły
  ``services/hr/placement_bonuses``. ``b2b_generated_contracts.recruiter_user_id``
  (z importu Excela) dostaje teraz osobę prowadzącą w chwili wygenerowania —
  adresata przypomnień o podpisie.
* ``notificationtype`` ``b2b_agreement_ready`` — dzwonek dla prowadzącego, gdy
  umowę za niego wygenerował ktoś inny.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0524_agreement_admin_details"
down_revision = "0522_candidate_client_forms"
branch_labels = None
depends_on = None

COLUMNS = (
    "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS is_replacement BOOLEAN",
    "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS replaced_contract_id "
    "INTEGER REFERENCES contracts(id) ON DELETE SET NULL",
    "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS fte NUMERIC(3, 2)",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS is_replacement BOOLEAN",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS replaced_contract_id "
    "INTEGER REFERENCES contracts(id) ON DELETE SET NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS fte NUMERIC(3, 2)",
    "CREATE INDEX IF NOT EXISTS ix_contracts_replaced_contract_id "
    "ON contracts (replaced_contract_id)",
)

CONSTRAINTS = (
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_fte
            CHECK (fte IS NULL OR fte IN (1, 0.75, 0.5, 0.25));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE b2b_generated_contracts
            ADD CONSTRAINT ck_b2b_generated_contracts_replacement
            CHECK (replaced_contract_id IS NULL OR is_replacement IS TRUE);
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE contracts
            ADD CONSTRAINT ck_contracts_fte
            CHECK (fte IS NULL OR fte IN (1, 0.75, 0.5, 0.25));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
    """DO $$ BEGIN
        ALTER TABLE contracts
            ADD CONSTRAINT ck_contracts_replacement
            CHECK (
                (replaced_contract_id IS NULL OR is_replacement IS TRUE)
                AND (replaced_contract_id IS NULL OR replaced_contract_id <> id)
            );
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
)

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'b2b_agreement_ready'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'b2b_agreement_ready'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0524 odmawia: notifications ma wpisy b2b_agreement_ready, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in (*COLUMNS, *CONSTRAINTS):
        op.execute(statement)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for table in ("contracts", "b2b_generated_contracts"):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_fte")
        op.execute(
            f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS ck_{table}_replacement"
        )
    op.execute("DROP INDEX IF EXISTS ix_contracts_replaced_contract_id")
    for table in ("contracts", "b2b_generated_contracts"):
        for column in ("fte", "replaced_contract_id", "is_replacement"):
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
