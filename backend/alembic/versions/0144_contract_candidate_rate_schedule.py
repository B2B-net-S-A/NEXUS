"""Effective-dated candidate-rate schedule for contracts.

Revision ID: 0144_contract_candidate_rate_schedule
Revises: 0143_candidate_search_fts, 0143_invalidate_match_score_cache
Create Date: 2026-06-24

``contract_candidate_rates`` — historia stawek kandydata per kontrakt. Każdy
wiersz to krok harmonogramu: ``rate`` obowiązująca od ``effective_from``
("Obowiązuje od"). Aktualna stawka liczona przy odczycie (najpóźniejszy wpis
``effective_from <= dziś``) — bez background joba.

Ta migracja **scala dwa równoległe heady** (``0143_candidate_search_fts`` +
``0143_invalidate_match_score_cache``) — po niej ``alembic upgrade head`` ma
jeden head. Istniejące kontrakty nie mają wpisów; ``Contract.rate_candidate``
zostaje jako legacy fallback, więc zmiana jest wstecznie kompatybilna.

Idempotent: CREATE TABLE / INDEX z IF NOT EXISTS — współgra z entrypoint
``alembic upgrade heads`` oraz DEBUG ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0144_contract_candidate_rate_schedule"
down_revision = (
    "0143_candidate_search_fts",
    "0143_invalidate_match_score_cache",
)
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS contract_candidate_rates (
            id              SERIAL PRIMARY KEY,
            contract_id     INTEGER NOT NULL
                                REFERENCES contracts(id) ON DELETE CASCADE,
            rate            INTEGER NOT NULL,
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
        "CREATE INDEX IF NOT EXISTS ix_contract_candidate_rates_contract_id "
        "ON contract_candidate_rates (contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_candidate_rates_effective_from "
        "ON contract_candidate_rates (effective_from)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_contract_candidate_rates_id "
        "ON contract_candidate_rates (id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS contract_candidate_rates")
