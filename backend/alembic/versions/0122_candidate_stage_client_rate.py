"""Stawka do klienta — client sell rate per recruitment on candidate_stages

Revision ID: 0122_candidate_stage_client_rate
Revises: 0121_candidate_stages_hired_partial_idx
Create Date: 2026-06-02 00:00:00.000000

Context:
    Recruiter potrzebuje zapisać cenę, za jaką kandydat został wysłany do
    klienta na danej rekrutacji (sell rate). Dotąd przechowywaliśmy tylko
    `expected_rate_*` (oczekiwania kandydata) oraz finalne rate'y na Contract
    (dopiero po `hired`). Brakowało pola na cenę zaproponowaną klientowi w
    trakcie rekrutacji (moment `cv_sent`).

What this migration does:
    Dodaje 3 kolumny do `candidate_stages` lustrzane do `expected_rate_*`:
      - client_rate_value    NUMERIC(10, 2)
      - client_rate_unit     rateunit  (reuse istniejącego PG enuma)
      - client_rate_currency VARCHAR(3)

    Wartość trzymana na najnowszym CandidateStage danej (candidate, job);
    odczyt = ostatnia niepusta wartość w obrębie rekrutacji (analogicznie do
    sposobu czytania expected_rate w candidates.py).

Safety net:
    Wszystko idempotentne (`ADD COLUMN IF NOT EXISTS`). Enum `rateunit` już
    istnieje (z modułu contracts / migracji 0056) — nie tworzymy nowego typu.
"""

from alembic import op


revision = "0122_candidate_stage_client_rate"
down_revision = "0121_candidate_stages_hired_partial_idx"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS client_rate_value NUMERIC(10, 2) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS client_rate_unit rateunit NULL
        """
    )
    op.execute(
        """
        ALTER TABLE candidate_stages
            ADD COLUMN IF NOT EXISTS client_rate_currency VARCHAR(3) NULL
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE candidate_stages DROP COLUMN IF EXISTS client_rate_currency"
    )
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS client_rate_unit")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS client_rate_value")
