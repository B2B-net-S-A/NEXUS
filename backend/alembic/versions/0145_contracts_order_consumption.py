"""Zużycie zamówienia: ilość + jednostka (RBH/MD) na kontrakcie.

Revision ID: 0145_contracts_order_consumption
Revises: 0144_contract_candidate_rate_schedule
Create Date: 2026-06-24

Dodaje do tabeli ``contracts`` pola pod "Zużycie zamówienia" (formularz
"Kontrakty → Nowy kontrakt"), wymagane przez klientów rozliczających się
per-zamówienie (BNP, BIK, Polkomtel, Bosch):

  * ``order_consumption`` (NUMERIC(10,2)) — ilość zużyta z zamówienia.
  * ``order_consumption_unit`` (enum ``orderconsumptionunit``) — jednostka
    zużycia: ``rbh`` (roboczogodziny) / ``md`` (osobodni). Oba pola nullable,
    wypełniane razem.

Chainuje liniowo za ``0144_contract_candidate_rate_schedule`` (która scaliła
dwie głowy z poziomu 0143), więc żywy łańcuch ma jedną głowę.

Idempotent: ``DO $$ IF NOT EXISTS $$`` dla enuma + ``ADD COLUMN IF NOT
EXISTS`` — współgra z entrypoint safety-net oraz z DEBUG
``Base.metadata.create_all``.
"""

from alembic import op

revision = "0145_contracts_order_consumption"
down_revision = "0144_contract_candidate_rate_schedule"
branch_labels = None
depends_on = None


_ORDER_CONSUMPTION_UNITS = ("rbh", "md")


def upgrade() -> None:
    # ── Enum type (idempotent) ────────────────────────────────────────────
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'orderconsumptionunit') THEN
                CREATE TYPE orderconsumptionunit AS ENUM (
                    {", ".join(f"'{v}'" for v in _ORDER_CONSUMPTION_UNITS)}
                );
            END IF;
        END$$;
        """
    )

    # ── contracts: order consumption columns ──────────────────────────────
    for column_sql in (
        "ADD COLUMN IF NOT EXISTS order_consumption NUMERIC(10, 2)",
        "ADD COLUMN IF NOT EXISTS order_consumption_unit orderconsumptionunit",
    ):
        op.execute(f"ALTER TABLE contracts {column_sql}")


def downgrade() -> None:
    for column in (
        "order_consumption_unit",
        "order_consumption",
    ):
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TYPE IF EXISTS orderconsumptionunit")
