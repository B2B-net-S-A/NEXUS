"""„Klient nie wymaga dokumentów” przy liście dokumentów do startu (20.11.2026).

Revision ID: 0745_client_start_documents_not_required
Revises: 0744_b2b_document_preliminary_b2b

Licznik „Start u klienta: N z M ustalone” (decyzja Artura z 20.11.2026) liczy
dokumenty jako ustalone, gdy lista ma pozycję albo ktoś jawnie zaznaczył, że
klient nic nie wymaga. Dwie kolumny przy kliencie (kiedy, kto). DDL ma jedno
źródło z siatką w ``entrypoint.sh`` (``services/start_documents_schema.py``).
"""

from alembic import op

from app.services.start_documents_schema import NOT_REQUIRED_DDL

revision = "0745_client_start_documents_not_required"
down_revision = "0744_b2b_document_preliminary_b2b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in NOT_REQUIRED_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "ALTER TABLE clients DROP COLUMN IF EXISTS start_documents_not_required_by"
    )
    op.execute(
        "ALTER TABLE clients DROP COLUMN IF EXISTS start_documents_not_required_at"
    )
