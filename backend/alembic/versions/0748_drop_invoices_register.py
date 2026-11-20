"""Usunięcie pustego rejestru faktur: tabela `invoices` i enumy `invoicedirection`, `invoicestatus`.

Revision ID: 0748_drop_invoices_register
Revises: 0747_client_start_documents_not_required

Decyzja Artura z 20.11.2026. Ręczny rejestr faktur kontraktu (0026, Phase 9 C1)
od powstania 17.04.2026 nie dostał na produkcji ani jednego wiersza; faktury
przychodzą z KSeF (`client_sales_invoices`, `client_contractor_invoices`).
Trasy, model, scope'y API v1, zdarzenia i surowe odczyty tabeli zdjął #3661.
Na produkcji (20.11.2026) na tabelę nie wskazuje żaden klucz obcy, nie ma na
niej triggerów ani widoków, a enumów nie używa inna kolumna, więc instrukcje
idą bez CASCADE: nieznana zależność przerwie migrację głośno. Lustro jest
w `entrypoint.sh`; pilnuje go `tests/test_drop_invoices_register_mirror.py`.
"""

from alembic import op

revision = "0748_drop_invoices_register"
down_revision = "0747_client_start_documents_not_required"
branch_labels = None
depends_on = None

TABLE_GROUPS = (("invoices",),)
ENUMS = ("invoicedirection", "invoicestatus")


def drop_statements() -> list[str]:
    tables = [f"DROP TABLE IF EXISTS {', '.join(group)}" for group in TABLE_GROUPS]
    return [*tables, *(f"DROP TYPE IF EXISTS {name}" for name in ENUMS)]


def upgrade() -> None:
    # zgodne-wstecz: tabeli nie czyta kod od #3661 (wdrożony 20.11.2026)
    for statement in drop_statements():
        op.execute(statement)


def downgrade() -> None:
    """Bez cofania schematem: tabela była pusta od powstania."""
