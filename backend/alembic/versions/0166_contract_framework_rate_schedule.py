"""Effective-dated framework-rate schedule for contracts.

Revision ID: 0166_contract_framework_rate_schedule
Revises: 0165_strip_traffit_employed_marker
Create Date: 2026-07-15

``contract_framework_rates`` — historia stawek z umowy ramowej per kontrakt,
bliźniacza do ``contract_candidate_rates`` (0144) i ``contract_client_rates``
(0151). Każdy wiersz to krok harmonogramu: ``rate`` obowiązująca od
``effective_from`` ("Obowiązuje od"), z opcjonalnym ``effective_to``
("Obowiązuje do", doradcze). Aktualna stawka liczona przy odczycie
(najpóźniejszy wpis ``effective_from <= dziś``) — bez background joba.

Powód: dotąd „Stawka z umowy ramowej" była pojedynczą wartością (kolumna
``contracts.framework_rate``). Klient bywa, że zmienia stawkę ramową w trakcie
współpracy — ten harmonogram pozwala zaplanować zmianę od konkretnej daty w
formularzach „Nowy kontrakt" i „Edycja kontraktu". Stawka ramowa NIE wchodzi do
marży (to wartość referencyjna), więc harmonogram trzyma tylko kolumnę
``framework_rate`` zsynchronizowaną z krokiem obowiązującym dziś.

``rate`` jako NUMERIC(12,2) — zgodnie z kolumną ``contracts.framework_rate``
(grosze, np. 215,60 — migracja 0157).

Istniejące kontrakty nie mają wpisów; ``Contract.framework_rate`` zostaje jako
legacy fallback, więc zmiana jest wstecznie kompatybilna (zero backfillu).

Idempotent: CREATE TABLE / INDEX z IF NOT EXISTS — współgra z entrypoint
``alembic upgrade heads`` oraz DEBUG ``Base.metadata.create_all``. Mirror w
``entrypoint.sh`` (_COLUMN_STATEMENTS) na wypadek multi-head driftu na prod.
"""

from alembic import op

revision = "0166_contract_framework_rate_schedule"
down_revision = "0165_strip_traffit_employed_marker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_framework_rates (
            id              SERIAL PRIMARY KEY,
            contract_id     INTEGER NOT NULL
                                REFERENCES contracts(id) ON DELETE CASCADE,
            rate            NUMERIC(12, 2) NOT NULL,
            effective_from  DATE NOT NULL,
            effective_to    DATE NULL,
            note            TEXT NULL,
            created_by      INTEGER NULL
                                REFERENCES users(id) ON DELETE SET NULL,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_framework_rates_contract_id "
        "ON contract_framework_rates (contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_framework_rates_effective_from "
        "ON contract_framework_rates (effective_from)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_framework_rates_id "
        "ON contract_framework_rates (id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_framework_rates")
