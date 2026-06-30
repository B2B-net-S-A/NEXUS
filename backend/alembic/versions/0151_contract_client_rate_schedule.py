"""Effective-dated client-rate schedule for contracts.

Revision ID: 0151_contract_client_rate_schedule
Revises: 0150_invalidate_match_cache_neutral065
Create Date: 2026-06-30

``contract_client_rates`` — historia stawek klienta per kontrakt, bliźniacza do
``contract_candidate_rates`` (migracja 0144). Każdy wiersz to krok harmonogramu:
``rate`` obowiązująca od ``effective_from`` ("Obowiązuje od"). Aktualna stawka
liczona przy odczycie (najpóźniejszy wpis ``effective_from <= dziś``) — bez
background joba.

Powód: aneks „Zmień stawkę" z datą wejścia w życie w przyszłości nadpisywał
``contracts.rate_client`` natychmiast, więc marża bieżącego zamówienia liczyła
się od nowej stawki. Po tej zmianie nowa stawka klienta ląduje jako krok
harmonogramu i obowiązuje dopiero od daty z aneksu (stara stawka trzyma do końca
trwającego zamówienia), dokładnie tak jak już działa stawka kandydata.

Istniejące kontrakty nie mają wpisów; ``Contract.rate_client`` zostaje jako
legacy fallback, więc zmiana jest wstecznie kompatybilna (zero backfillu).

``rate`` od razu jako NUMERIC(12,3) — docelowy typ kolumn stawek po migracjach
0148/0149 (ułamkowe stawki godzinowe, np. Alior 164,375 zł/h).

Idempotent: CREATE TABLE / INDEX z IF NOT EXISTS — współgra z entrypoint
``alembic upgrade heads`` oraz DEBUG ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0151_contract_client_rate_schedule"
down_revision = "0150_invalidate_match_cache_neutral065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_client_rates (
            id              SERIAL PRIMARY KEY,
            contract_id     INTEGER NOT NULL
                                REFERENCES contracts(id) ON DELETE CASCADE,
            rate            NUMERIC(12, 3) NOT NULL,
            effective_from  DATE NOT NULL,
            note            TEXT NULL,
            created_by      INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_client_rates_contract_id "
        "ON contract_client_rates (contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_client_rates_effective_from "
        "ON contract_client_rates (effective_from)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_client_rates_id "
        "ON contract_client_rates (id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_client_rates")
