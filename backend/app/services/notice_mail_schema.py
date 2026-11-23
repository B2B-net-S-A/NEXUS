"""Wypowiedzenia z poczty (decyzje Artura 23.11.2026): SQL migracji ``0755_notice_mail`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0755_notice_mail.py``
i ``entrypoint.sh``. Każda instrukcja idempotentna.

Tabele:

* ``notice_mail_proposals`` — co czytnik spraw rozpoznał w mailu
  (wypowiedzenie konsultanta, klient kończy, zmiana daty, wycofanie) i jaki
  komplet zmian proponuje. Automat niczego nie zapisuje w kontrakcie ani
  zamówieniu: karta woła istniejące trasy, a tu zostaje decyzja człowieka.
* ``known_sender_emails`` — adresy, z których konsultant pisze, a których nie
  ma w kontrakcie ani profilu (np. ``imie.nazwisko@b2bnetwork.pl`` z home.pl:
  23.11 żaden z 510 żywych kontraktów nie miał takiego adresu). Wpis powstaje
  dopiero po potwierdzeniu człowieka.
* ``archived_mails`` — historia administracja@ z home.pl (archiwum z 20.11,
  5 875 maili) przypięta do kontraktów; bez zakładania spraw.
"""

from __future__ import annotations

KINDS: tuple[str, ...] = (
    "consultant_notice",
    "client_termination",
    "date_change",
    "withdrawal",
)
STATUSES: tuple[str, ...] = ("pending", "confirmed", "rejected", "superseded")
SENDER_SOURCES: tuple[str, ...] = ("notice_confirm", "case_link")
BODY_MAX = 20_000


def _quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS notice_mail_proposals (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
    message_id INTEGER NULL REFERENCES admin_case_messages(id) ON DELETE SET NULL,
    kind VARCHAR(24) NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'pending',
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    order_id INTEGER NULL REFERENCES client_orders(id) ON DELETE SET NULL,
    delivered_on DATE NULL,
    proposed_last_day DATE NULL,
    client_end_date DATE NULL,
    contract_number VARCHAR(32) NULL,
    cpro_number VARCHAR(32) NULL,
    match JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    decision JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_notice_mail_proposals_message UNIQUE (message_id),
    CONSTRAINT ck_notice_mail_proposals_kind CHECK (kind IN ({_quoted(KINDS)})),
    CONSTRAINT ck_notice_mail_proposals_status CHECK (status IN ({_quoted(STATUSES)})),
    CONSTRAINT ck_notice_mail_proposals_decided CHECK (
        (status = 'pending') = (decided_at IS NULL)
    )
)""",
    f"""CREATE TABLE IF NOT EXISTS known_sender_emails (
    email VARCHAR(320) PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    source VARCHAR(16) NOT NULL,
    confirmed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_known_sender_emails_lower CHECK (email = lower(btrim(email))),
    CONSTRAINT ck_known_sender_emails_source CHECK (source IN ({_quoted(SENDER_SOURCES)}))
)""",
    """CREATE TABLE IF NOT EXISTS archived_mails (
    id SERIAL PRIMARY KEY,
    mailbox VARCHAR(32) NOT NULL,
    folder VARCHAR(200) NOT NULL,
    sha256 CHAR(64) NOT NULL,
    received_at TIMESTAMPTZ NULL,
    message_id VARCHAR(512) NULL,
    sender_email VARCHAR(320) NULL,
    sender_name VARCHAR(200) NULL,
    to_emails JSONB NOT NULL DEFAULT '[]'::jsonb,
    subject VARCHAR(500) NULL,
    body_text TEXT NOT NULL DEFAULT '',
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    eml_path VARCHAR(500) NULL,
    candidate_id INTEGER NULL REFERENCES candidates(id) ON DELETE SET NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    match_reason VARCHAR(24) NULL,
    imported_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_archived_mails_sha256 UNIQUE (sha256)
)""",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_notice_mail_proposals_case "
    "ON notice_mail_proposals (case_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_notice_mail_proposals_contract "
    "ON notice_mail_proposals (contract_id) WHERE contract_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_known_sender_emails_candidate "
    "ON known_sender_emails (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_archived_mails_contract "
    "ON archived_mails (contract_id, received_at) WHERE contract_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_archived_mails_candidate "
    "ON archived_mails (candidate_id) WHERE candidate_id IS NOT NULL",
)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *INDEX_DDL)
DROP_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS archived_mails",
    "DROP TABLE IF EXISTS known_sender_emails",
    "DROP TABLE IF EXISTS notice_mail_proposals",
)
