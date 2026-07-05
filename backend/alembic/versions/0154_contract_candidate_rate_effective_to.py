"""Add "Obowiązuje do" (effective_to) to the candidate-rate schedule.

Revision ID: 0154_contract_candidate_rate_effective_to
Revises: 0153_client_min_sprawiedliwosci
Create Date: 2026-07-05

Dodaje kolumnę ``effective_to`` (DATE, nullable) do ``contract_candidate_rates``
pod „stawkę progresywną" w formularzu Edycja kontraktu — recruiter planuje z góry
kolejne etapy stawki kandydata, każdy z oknem „Obowiązuje od" / „Obowiązuje do"
(np. trzy stawki co 3–6 miesięcy).

Kolumna jest doradcza: aktualna stawka wciąż liczona z ``effective_from`` (patrz
``ContractCandidateRate`` docstring + ``Contract._resolve_scheduled_rate``), więc
istniejące harmonogramy zachowują się bez zmian. ``effective_to`` służy do
wyświetlania i planowania okien.

Idempotent: ``ADD COLUMN IF NOT EXISTS`` — współgra z entrypoint
``alembic upgrade heads`` oraz DEBUG ``Base.metadata.create_all``.
"""

from alembic import op

revision = "0154_contract_candidate_rate_effective_to"
down_revision = "0153_client_min_sprawiedliwosci"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE contract_candidate_rates "
        "ADD COLUMN IF NOT EXISTS effective_to DATE"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE contract_candidate_rates DROP COLUMN IF EXISTS effective_to"
    )
