"""contractdocumenttype enum += 'order' (Zamówienie)

Revision ID: 0160_contract_document_type_order
Revises: 0159_candidate_search_doc_unaccented
Create Date: 2026-07-13 13:00:00.000000

Dodaje nowy typ dokumentu „Zamówienie" do listy w sekcji Dokumenty na
kontrakcie (obok Umowa/Aneks/NDA/NIP/Zaświadczenie ZUS/Polisa OC/Inne).

To OSOBNY typ od encji ``ClientOrder`` (Zamówienie od klienta) — tutaj chodzi
wyłącznie o kategorię załączonego pliku (PDF zamówienia) na kontrakcie.

PG nie pozwala na ADD VALUE w bloku transakcyjnym — używamy `autocommit_block`
(wzorzec z 0054_marketplace_notification_type).

Downgrade = no-op — PG nie wspiera usuwania wartości enum bez rekreacji typu,
a dane w `contract_documents.doc_type` mogą już na nią wskazywać.

UWAGA: wartość jest też zmirrorowana w `backend/entrypoint.sh` `_ENUM_STATEMENTS`
(safety-net na prod przy multi-head alembic).
"""

from alembic import op


revision = "0160_contract_document_type_order"
down_revision = "0159_candidate_search_doc_unaccented"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE contractdocumenttype "
            "ADD VALUE IF NOT EXISTS 'order'"
        )


def downgrade() -> None:
    # No-op — patrz docstring.
    pass
