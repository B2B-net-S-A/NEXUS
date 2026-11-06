"""Kandydat wskazany przez klienta: bez premii z placementu.

Revision ID: 0656_client_referral_contract
Revises: 0655_job_recruiter_channels

Decyzja Artura z 06.11.2026 (zgłoszenie Płac): za kandydata, którego klient
wskazał do przepuszczenia przez nas, premii z placementu nie dostaje nikt —
ani rekruter, ani Delivery Lead — a kontrakt nie liczy się do celu premii 200%.

``is_client_referral`` w wierszu umowy (wpisuje Generator, domyślnie „Nie”)
i w kontrakcie (kopia przy podpisie fill-only, jak replacement i FTE).
NULL = nie wiadomo (umowy i kontrakty sprzed tej migracji) i liczy się jak „Nie”.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0656_client_referral_contract"
down_revision = "0655_job_recruiter_channels"
branch_labels = None
depends_on = None

COLUMNS = (
    "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS "
    "is_client_referral BOOLEAN",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS is_client_referral BOOLEAN",
)


def upgrade() -> None:
    for stmt in COLUMNS:
        op.execute(stmt)


def downgrade() -> None:
    op.execute("ALTER TABLE contracts DROP COLUMN IF EXISTS is_client_referral")
    op.execute(
        "ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS is_client_referral"
    )
