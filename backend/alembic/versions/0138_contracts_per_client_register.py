"""Per-klient rejestr kontraktów: status prolongaty, nr projektu, model rozliczeń.

Revision ID: 0138_contracts_per_client_register
Revises: 0137_talent_pool_is_personal
Create Date: 2026-06-19

Dodaje do tabeli ``contracts`` kolumny pod per-klient rejestr kontraktów
(start: Nordea), dostępny na /contracts po wybraniu klienta:

  * ``project_code`` (VARCHAR 64) — numer/kod projektu po stronie klienta
    (osobny od naszego ``id``). ``project_name`` istnieje już wcześniej.
  * ``prolongation_status`` (enum) — forecast przedłużenia:
    unknown / yes / no / negotiate. Domyślnie ``unknown``.
  * ``engagement_model`` (enum) — time_based / hours_pool. Domyślnie
    ``time_based``. Pozwala mieszać kontrakty czasowe i godzinowe u jednego
    klienta.
  * ``hours_pool_total`` / ``hours_pool_consumed`` (INTEGER) — pula godzin do
    wykorzystania (tylko gdy engagement_model == hours_pool).

Idempotent: ``DO $$ IF NOT EXISTS $$`` dla enumów + ``ADD COLUMN IF NOT
EXISTS`` + ``CREATE INDEX IF NOT EXISTS`` — współgra z entrypoint safety-net
oraz z DEBUG ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0138_contracts_per_client_register"
down_revision = "0137_talent_pool_is_personal"
branch_labels = None
depends_on = None


_PROLONGATION_STATUSES = ("unknown", "yes", "no", "negotiate")
_ENGAGEMENT_MODELS = ("time_based", "hours_pool")


def upgrade() -> None:
    # ── Enum types (idempotent) ───────────────────────────────────────────
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'prolongationstatus') THEN
                CREATE TYPE prolongationstatus AS ENUM (
                    {", ".join(f"'{v}'" for v in _PROLONGATION_STATUSES)}
                );
            END IF;
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'engagementmodel') THEN
                CREATE TYPE engagementmodel AS ENUM (
                    {", ".join(f"'{v}'" for v in _ENGAGEMENT_MODELS)}
                );
            END IF;
        END$$;
        """
    )

    # ── contracts: register columns ───────────────────────────────────────
    for column_sql in (
        "ADD COLUMN IF NOT EXISTS project_code VARCHAR(64)",
        "ADD COLUMN IF NOT EXISTS prolongation_status prolongationstatus "
        "NOT NULL DEFAULT 'unknown'",
        "ADD COLUMN IF NOT EXISTS engagement_model engagementmodel "
        "NOT NULL DEFAULT 'time_based'",
        "ADD COLUMN IF NOT EXISTS hours_pool_total INTEGER",
        "ADD COLUMN IF NOT EXISTS hours_pool_consumed INTEGER DEFAULT 0",
    ):
        op.execute(f"ALTER TABLE contracts {column_sql}")

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contracts_prolongation_status "
        "ON contracts (prolongation_status)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_contracts_prolongation_status"
    )
    for column in (
        "hours_pool_consumed",
        "hours_pool_total",
        "engagement_model",
        "prolongation_status",
        "project_code",
    ):
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TYPE IF EXISTS engagementmodel")
    op.execute("DROP TYPE IF EXISTS prolongationstatus")
