"""Zamówienia z maila: przeznaczenie połączenia M365, dziennik załączników, stan pętli.

Revision ID: 0264_order_mail_ingest
Revises: 0263_group_type_no_client_ids

Ticket „Automatyczne pobieranie i przetwarzanie zamówień z maila
zamowienia@b2bnetwork.pl". Skrzynka kopii żyje w M365 i jest czytana przez
istniejący pipeline Graphowy — ale ten pipeline traktuje KAŻDE aktywne
połączenie jak skrzynkę rekrutera: uruchamia matcher kandydatów (temat
z nazwiskiem aktywnego konsultanta = trafienie), zakłada wiersze ``emails``
na osiach czasu kandydatów, backfilluje 12 miesięcy. Zamówienia klientów
wylądowałyby na osiach czasu kandydatów. Stąd ``m365_connections.purpose``:
``personal`` (dotychczasowe zachowanie, default) albo ``orders`` — połączenie
pomijane przez sync osobisty i czytane wyłącznie przez cienki reader
zamówień.

``order_mail_documents`` — jeden wiersz na załącznik (albo na wiadomość bez
PDF-a) z drabiną wyniku. Dwa CZĘŚCIOWE indeksy unikalne dają idempotencję
biegu przerwanego przez restart kontenera; duplikat TREŚCI (ten sam PDF
w nowym mailu) jest osobnym wpisem ``duplicate_attachment`` wskazującym na
pierwowzór, nie naruszeniem unikalności.

``order_mail_sync_state`` — jednowierszowy watermark pętli (id = 1).

Lustro DDL w ``entrypoint.sh`` — prod alembic bywa osierocony.
"""

from alembic import op

revision = "0264_order_mail_ingest"
down_revision = "0263_group_type_no_client_ids"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE m365_connections ADD COLUMN IF NOT EXISTS purpose "
        "VARCHAR(16) NOT NULL DEFAULT 'personal'"
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE m365_connections ADD CONSTRAINT ck_m365_connections_purpose
                CHECK (purpose IN ('personal', 'orders'));
        EXCEPTION WHEN duplicate_object THEN NULL; END $$
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_mail_documents (
            id SERIAL PRIMARY KEY,
            connection_id INTEGER NULL
                REFERENCES m365_connections(id) ON DELETE SET NULL,
            internet_message_id VARCHAR(998) NOT NULL,
            m365_message_id VARCHAR(512) NULL,
            received_at TIMESTAMPTZ NULL,
            sender_email VARCHAR(320) NULL,
            sender_domain VARCHAR(255) NULL,
            subject VARCHAR(1000) NULL,
            attachment_name VARCHAR(255) NULL,
            attachment_sha256 VARCHAR(64) NULL,
            attachment_size INTEGER NULL,
            storage_path VARCHAR(512) NULL,
            duplicate_of_id INTEGER NULL
                REFERENCES order_mail_documents(id) ON DELETE SET NULL,
            outcome VARCHAR(32) NOT NULL DEFAULT 'received',
            client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
            client_key VARCHAR(64) NULL,
            identification_method VARCHAR(16) NULL,
            identification_reason TEXT NULL,
            client_policy VARCHAR(128) NULL,
            extraction JSONB NULL,
            document_meta JSONB NULL,
            gate_verdict VARCHAR(16) NULL,
            gate_reasons JSONB NULL,
            proposal JSONB NULL,
            applied_order_id INTEGER NULL
                REFERENCES client_orders(id) ON DELETE SET NULL,
            applied_group_id INTEGER NULL
                REFERENCES client_order_groups(id) ON DELETE SET NULL,
            applied_at TIMESTAMPTZ NULL,
            applied_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            reviewed_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            reviewed_at TIMESTAMPTZ NULL,
            error TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_order_mail_documents_outcome CHECK (outcome IN (
                'received','ignored_no_pdf','ignored_sender','duplicate_attachment',
                'unrecognized_client','needs_review','auto_applied','applied',
                'dismissed','failed')),
            CONSTRAINT ck_order_mail_documents_gate_verdict
                CHECK (gate_verdict IS NULL OR gate_verdict IN ('auto','review'))
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_order_mail_documents_message_attachment "
        "ON order_mail_documents (internet_message_id, attachment_sha256) "
        "WHERE attachment_sha256 IS NOT NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_order_mail_documents_message_no_attachment "
        "ON order_mail_documents (internet_message_id) WHERE attachment_sha256 IS NULL"
    )
    for name, col in (
        ("ix_order_mail_documents_sha", "attachment_sha256"),
        ("ix_order_mail_documents_outcome", "outcome"),
        ("ix_order_mail_documents_client", "client_id"),
        ("ix_order_mail_documents_received", "received_at"),
        ("ix_order_mail_documents_connection_id", "connection_id"),
    ):
        op.execute(f"CREATE INDEX IF NOT EXISTS {name} ON order_mail_documents ({col})")
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS order_mail_sync_state (
            id INTEGER PRIMARY KEY,
            last_run_started_at TIMESTAMPTZ NULL,
            last_run_finished_at TIMESTAMPTZ NULL,
            last_status VARCHAR(20) NULL,
            last_error TEXT NULL,
            last_seen_received_at TIMESTAMPTZ NULL,
            stats JSONB NULL,
            updated_at TIMESTAMPTZ NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS order_mail_sync_state")
    op.execute("DROP TABLE IF EXISTS order_mail_documents")
    op.execute(
        "ALTER TABLE m365_connections DROP CONSTRAINT IF EXISTS ck_m365_connections_purpose"
    )
    op.execute("ALTER TABLE m365_connections DROP COLUMN IF EXISTS purpose")
