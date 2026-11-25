"""Dodatkowe numery nabywcy klienta (25.11.2026).

Revision ID: 0779_client_buyer_numbers
Revises: 0778_b2b_document_preliminary_jdg

Spółki grupy klienta (oddział, spółka leasingowa, fundusz emerytalny) fakturują
się pod własnym NIP-em albo VAT UE, a klient ma jedno ``clients.nip``. Tabela
``client_buyer_numbers`` trzyma kolejne numery; rejestr ``nip_registry`` czyta
ją obok ``clients.nip`` (decyzja Artura z 25.11.2026). DDL ma jedno źródło
z lustrem w ``entrypoint.sh`` (``services/client_invoicing/buyer_numbers_schema.py``).
"""

from alembic import op

from app.services.client_invoicing.buyer_numbers_schema import DDL

revision = "0779_client_buyer_numbers"
down_revision = "0778_b2b_document_preliminary_jdg"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS client_buyer_numbers")
