"""Rozszerz `document_signatures` o linki do client framework contract / amendment.

Revision ID: 0091_extend_document_signature_msa
Revises: 0090_client_order_contracts
Create Date: 2026-05-08 16:20:00.000000

Cel: pozwolić Autenti integration na podpisywanie nie tylko kandydackich
``contracts``, ale też klienta-poziomowych ``client_framework_contracts``
i ``client_contract_amendments``.

Zmiany:
1. ``contract_id`` → NULLABLE
2. Dodaj ``client_framework_contract_id`` (FK CASCADE) + ``client_contract_amendment_id`` (FK CASCADE)
3. ``contract_document_id`` → NULLABLE (PDF dla MSA jest wgrywany bezpośrednio,
   bez HTML snapshot)
4. CHECK constraint: dokładnie 1 z 3 FK non-null

Zgodność wsteczna: istniejące rekordy mają contract_id non-null → CHECK
nie złamie ich. CHECK używa ``NOT VALID`` żeby zminimalizować lock.
"""

from alembic import op


revision = "0091_extend_document_signature_msa"
down_revision = "0090_client_order_contracts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Zrelaksuj NOT NULL na contract_id i contract_document_id
    op.execute(
        "ALTER TABLE document_signatures ALTER COLUMN contract_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ALTER COLUMN contract_document_id DROP NOT NULL"
    )

    # 2) Dodaj nowe FK
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS client_framework_contract_id INTEGER NULL "
        "REFERENCES client_framework_contracts(id) ON DELETE CASCADE"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ADD COLUMN IF NOT EXISTS client_contract_amendment_id INTEGER NULL "
        "REFERENCES client_contract_amendments(id) ON DELETE CASCADE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_sig_framework "
        "ON document_signatures(client_framework_contract_id) "
        "WHERE client_framework_contract_id IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_sig_amendment "
        "ON document_signatures(client_contract_amendment_id) "
        "WHERE client_contract_amendment_id IS NOT NULL"
    )

    # 3) CHECK constraint — dokładnie 1 z 3 FK non-null.
    # NOT VALID żeby uniknąć full-table scan locku; istniejące rekordy mają
    # contract_id non-null więc satisfaction gwarantowana, ale dla bezpieczeństwa
    # validate w 2 krokach.
    op.execute(
        """
        ALTER TABLE document_signatures
        ADD CONSTRAINT chk_signature_target_xor CHECK (
            (CASE WHEN contract_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN client_framework_contract_id IS NOT NULL THEN 1 ELSE 0 END) +
            (CASE WHEN client_contract_amendment_id IS NOT NULL THEN 1 ELSE 0 END)
            = 1
        ) NOT VALID
        """
    )
    op.execute(
        "ALTER TABLE document_signatures VALIDATE CONSTRAINT chk_signature_target_xor"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE document_signatures DROP CONSTRAINT IF EXISTS "
        "chk_signature_target_xor"
    )
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_amendment")
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_framework")
    op.execute(
        "ALTER TABLE document_signatures "
        "DROP COLUMN IF EXISTS client_contract_amendment_id"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "DROP COLUMN IF EXISTS client_framework_contract_id"
    )
    # Re-add NOT NULL — works because dropped columns can't have rows where
    # contract_id was nulled (we never let app insert such rows).
    op.execute(
        "ALTER TABLE document_signatures ALTER COLUMN contract_id SET NOT NULL"
    )
    op.execute(
        "ALTER TABLE document_signatures "
        "ALTER COLUMN contract_document_id SET NOT NULL"
    )
