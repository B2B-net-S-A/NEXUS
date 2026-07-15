"""Contract: Line Manager name + Contracted Rate + Frame Agreement Rate.

Revision ID: 0140_contract_line_manager_rates
Revises: 0139_merge_0138_heads
Create Date: 2026-06-22

Dodaje do tabeli ``contracts`` trzy kolumny widoczne w formularzu
„Kontrakty → Dodaj → Dodaj kandydata" (FE: /contracts/new oraz
ContractRegisterDialog):

  * ``line_manager_name`` (VARCHAR 255) — imię i nazwisko Line Managera po
    stronie klienta (osoba, której bezpośrednio raportuje konsultant).
  * ``contracted_rate`` (INTEGER) — stawka zakontraktowana z konsultantem.
  * ``frame_agreement_rate`` (INTEGER) — stawka z umowy ramowej (frame
    agreement) z klientem.

Stawki w tej samej walucie/jednostce co reszta kontraktu (``currency`` /
``rate_unit``). Wszystkie nullable — pola opcjonalne.

Idempotent: ``ADD COLUMN IF NOT EXISTS`` — współgra z entrypoint safety-net
oraz z DEBUG ``Base.metadata.create_all`` (ten sam wzorzec co
``0138_contracts_per_client_register``).
"""

from alembic import op

revision = "0140_contract_line_manager_rates"
down_revision = "0139_merge_0138_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for column_sql in (
        "ADD COLUMN IF NOT EXISTS line_manager_name VARCHAR(255)",
        "ADD COLUMN IF NOT EXISTS contracted_rate INTEGER",
        "ADD COLUMN IF NOT EXISTS frame_agreement_rate INTEGER",
    ):
        op.execute(f"ALTER TABLE contracts {column_sql}")


def downgrade() -> None:
    for column in (
        "frame_agreement_rate",
        "contracted_rate",
        "line_manager_name",
    ):
        op.execute(f"ALTER TABLE contracts DROP COLUMN IF EXISTS {column}")
