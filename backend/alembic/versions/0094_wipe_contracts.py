"""Wipe all existing kandydackie Contracts (clean slate per Artur decision).

Revision ID: 0094_wipe_contracts
Revises: 0093_restructure_orders
Create Date: 2026-05-11 09:05:00.000000

Destructive: kasuje wszystkie kandydackie Contracty + powiązane przez CASCADE:
- contract_documents, contract_amendments, contract_equipment
- contract_onboarding_items, invoices (FK cascade)
- document_signatures (gdzie target=contract_id)

Idempotent: jeśli już pusta tabela, no-op.
Downgrade: NIE PRZYWRACA DANYCH (zniszczone dane są permanentne).

Świadoma decyzja użytkownika 2026-05-11 (memory `feedback_autonomy`):
Artur explicitly potwierdził "wykasuj je" — 11 kandydackich Contractów to
seed/test data, czysty start pod nowy model.
"""

from alembic import op


revision = "0094_wipe_contracts"
down_revision = "0093_restructure_orders"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CASCADE kasuje powiązane (FK ON DELETE CASCADE):
    # - contract_documents → contracts (CASCADE)
    # - contract_amendments → contracts (CASCADE)
    # - contract_equipment → contracts (CASCADE)
    # - contract_onboarding_items → contracts (CASCADE)
    # - invoices → contracts (CASCADE)
    # - document_signatures (gdzie contract_id != NULL) → contracts (CASCADE)
    op.execute("DELETE FROM contracts")


def downgrade() -> None:
    # Permanent data destruction — no restore path.
    # Manual restore z backupu Hetzner volume jeśli rzeczywiście potrzeba.
    pass
