"""Autenti e-signature integration — document_signatures + events tables.

Revision ID: 0079_autenti_signatures
Revises: 0078_password_reset_infrastructure
Create Date: 2026-05-07 14:00:00.000000

Wprowadza dwie nowe tabele dla integracji z platformą Autenti
(polski operator e-podpisów, eIDAS-zgodny):

1. ``document_signatures`` — jeden wiersz per Autenti document_process.
   Kontrakt może mieć wiele wysyłek (re-send po rejection/withdrawal),
   stąd osobna tabela zamiast kolumn na ``contracts``.
2. ``document_signature_events`` — append-only log webhooków z Autenti.
   Idempotency-by-DB: ``event_id`` UNIQUE → replay fails na INSERT,
   handler łapie ``IntegrityError`` i odpowiada ``{"status": "duplicate"}``.

Plus rozszerzenie enum ``notificationtype`` o 4 wartości dla powiadomień
in-app/email po wysyłce, podpisaniu, odmowie, niepowodzeniu.

Safety net (zgodnie z konwencją 0078 + project_kpi_coach_enum_gotcha
memory): ``ALTER TYPE … ADD VALUE`` w autocommit_block, ``CREATE TABLE``
z ``IF NOT EXISTS``. Downgrade dropuje tabele i typ; enum ``notificationtype``
values pozostają (PG nie wspiera usuwania enum values bez rekreacji typu).
"""

from alembic import op


revision = "0080_autenti_signatures"
down_revision = "0079_candidate_documents_storage_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) Rozszerz enum NotificationType (PG: ADD VALUE wymaga autocommit).
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_sent'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_signed'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_rejected'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'signature_failed'"
        )

    # 2) signaturestatus enum (CREATE TYPE IF NOT EXISTS unsupported in PG;
    # use DO $$ guard).
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'signaturestatus') THEN
                CREATE TYPE signaturestatus AS ENUM (
                    'draft', 'sending', 'sent', 'in_progress',
                    'completed', 'rejected', 'withdrawn', 'failed', 'expired'
                );
            END IF;
        END $$
        """
    )

    # 3) document_signatures
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_signatures (
            id SERIAL PRIMARY KEY,
            contract_id INTEGER NOT NULL
                REFERENCES contracts(id) ON DELETE CASCADE,
            contract_document_id INTEGER NOT NULL
                REFERENCES contract_documents(id) ON DELETE RESTRICT,
            autenti_process_id VARCHAR(64) UNIQUE,
            autenti_signature_type VARCHAR(16) NOT NULL DEFAULT 'SES',
            status signaturestatus NOT NULL DEFAULT 'draft',
            sent_at TIMESTAMPTZ NULL,
            completed_at TIMESTAMPTZ NULL,
            expires_at TIMESTAMPTZ NULL,
            sender_user_id INTEGER NOT NULL REFERENCES users(id),
            signer_email VARCHAR(255) NOT NULL,
            signer_first_name VARCHAR(120) NOT NULL,
            signer_last_name VARCHAR(120) NOT NULL,
            signer_phone VARCHAR(30) NULL,
            signed_document_id INTEGER NULL
                REFERENCES contract_documents(id) ON DELETE SET NULL,
            signed_document_url VARCHAR(1000) NULL,
            last_error TEXT NULL,
            retry_count SMALLINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_sig_contract "
        "ON document_signatures(contract_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_sig_status ON document_signatures(status)"
    )
    # Partial index — szybki lookup webhook handlera po Autenti process_id.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_sig_autenti_process "
        "ON document_signatures(autenti_process_id) "
        "WHERE autenti_process_id IS NOT NULL"
    )

    # 4) document_signature_events — append-only audit + idempotency.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS document_signature_events (
            id SERIAL PRIMARY KEY,
            signature_id INTEGER NOT NULL
                REFERENCES document_signatures(id) ON DELETE CASCADE,
            event_id VARCHAR(128) NOT NULL,
            event_type VARCHAR(64) NOT NULL,
            status VARCHAR(32) NULL,
            payload JSONB NOT NULL,
            received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            processed_at TIMESTAMPTZ NULL
        )
        """
    )
    # Insert-time idempotency — replays fail na INSERT, handler odpowiada
    # `{"status": "duplicate"}`.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_doc_sig_event_unique "
        "ON document_signature_events(event_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_doc_sig_event_signature "
        "ON document_signature_events(signature_id)"
    )


def downgrade() -> None:
    # Dropy odwrotne — enum 'notificationtype' values pozostają (PG limit).
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_event_signature")
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_event_unique")
    op.execute("DROP TABLE IF EXISTS document_signature_events")
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_autenti_process")
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_status")
    op.execute("DROP INDEX IF EXISTS ix_doc_sig_contract")
    op.execute("DROP TABLE IF EXISTS document_signatures")
    op.execute("DROP TYPE IF EXISTS signaturestatus")
