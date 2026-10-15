"""Stawka z bieżącej umowy w „Stawce od”: wyzwalacze kolejki przeliczeń.

Revision ID: 0448_rate_from_contracts
Revises: 0447_job_previous_recruiters

Dopóki osoba ma żywą umowę, „Stawka od” = stawka konsultanta z tej umowy
(decyzje D4/D5 Artura, 15.10.2026). Zmiana umowy albo harmonogramu jej stawek
kolejkuje przeliczenie kandydata; jednorazowo osoby z żywymi umowami trafiają
do kolejki.

SQL ma jedno źródło (``app/services/contract_rate_from_schema.py``) — ten sam
moduł importuje ``entrypoint.sh``.
"""

from alembic import op

from app.services import contract_rate_from_schema as schema

revision = "0448_rate_from_contracts"
down_revision = "0447_job_previous_recruiters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_rate_from_contracts ON contracts")
    op.execute("DROP FUNCTION IF EXISTS trg_rate_from_contracts()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_rate_from_contract_rates ON contract_candidate_rates"
    )
    op.execute("DROP FUNCTION IF EXISTS trg_rate_from_contract_rates()")
