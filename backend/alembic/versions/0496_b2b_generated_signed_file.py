"""Podpisany plik umowy B2B przy wierszu rejestru Generatora.

Revision ID: 0496_b2b_generated_signed_file
Revises: 0495_playbook_verified_required

* ``b2b_generated_contracts.signed_document_id`` — dokument kontraktu
  (``contract_documents``) z podpisanym egzemplarzem umowy, dołączony przy
  „Oznacz jako podpisaną” albo później z wiersza rejestru. Do 21.10.2026
  potwierdzenie podpisu było samą deklaracją: podpisany PDF krążył mailem
  i lądował poza NEXUSEM (zgłoszenie Administracji).

Usunięcie dokumentu w zakładce Dokumenty zeruje kolumnę (``ON DELETE SET NULL``).
Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony).
"""

from alembic import op

revision = "0496_b2b_generated_signed_file"
down_revision = "0495_playbook_verified_required"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contracts ADD COLUMN IF NOT EXISTS "
        "signed_document_id INTEGER REFERENCES contract_documents(id) "
        "ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE b2b_generated_contracts DROP COLUMN IF EXISTS signed_document_id"
    )
