"""„Ludzie w NEXUSIE” — Sprawy administracja@: SQL migracji ``0460_admin_cases`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0460_admin_cases.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Zakres: sprawy, wiadomości, komentarze, stan czytnika skrzynki.

Kontrakt modułu (czyta go agregator i test łańcucha):

* ``TABLE_DDL`` — ``CREATE TABLE IF NOT EXISTS`` nowych tabel (VARCHAR + CHECK,
  bez nowych typów enum),
* ``COLUMN_DDL`` — ``ALTER TABLE … ADD COLUMN IF NOT EXISTS`` w istniejących tabelach,
* ``INDEX_DDL`` — ``CREATE [UNIQUE] INDEX IF NOT EXISTS``,
* ``CONSTRAINT_DDL`` — ograniczenia dokładane do ISTNIEJĄCYCH tabel (idempotentne bloki ``DO``),
* ``DATA_DDL`` — zasiewy i znaczniki jednorazowe (idempotentne),
* ``TABLES`` — nowe tabele w kolejności tworzenia (downgrade kasuje odwrotnie),
* ``DOWNGRADE_DDL`` — sprzątanie kolumn/ograniczeń w istniejących tabelach.

Każda instrukcja musi być idempotentna: entrypoint wykonuje je przy każdym starcie.

Tabele:

* ``admin_cases`` — sprawa skrzynki administracja@ (kanban). ``source_key``
  UNIQUE czyni idempotentnymi automaty (nowy kontrakt, odejście, mail) i import
  z Compassa; sprawa ręczna go nie ma. ``closed_at`` stoi wtedy i tylko wtedy,
  gdy sprawa jest zrobiona albo zamknięta (Compass trzymał ``resolved_at``
  osobno od statusu i bywały rozjazdy).
* ``admin_case_messages`` — maile przypięte do sprawy (treść tekstowa po
  oczyszczeniu, załączniki tylko jako metadane). ``graph_message_id`` UNIQUE:
  drugi przebieg czytnika niczego nie dubluje.
* ``admin_case_comments`` — notatki obsługi.
* ``admin_mail_ingest_state`` — jeden wiersz: znacznik odebranych maili,
  ostatni przebieg i błąd (sonda i ekran stanu czytnika).
"""

from __future__ import annotations

AREAS: tuple[str, ...] = (
    "onboarding",
    "offboarding",
    "negotiation",
    "administration",
    "marketing",
    "other",
)
PRIORITIES: tuple[str, ...] = ("P1", "P2", "P3")
#: Kolejność kolumn kanbanu; ``done`` i ``closed`` to stany końcowe.
STATUSES: tuple[str, ...] = ("new", "in_progress", "waiting", "done", "closed")
TERMINAL_STATUSES: tuple[str, ...] = ("done", "closed")
SOURCES: tuple[str, ...] = ("manual", "mail", "contract", "lifecycle", "compass_import")
RUN_STATUSES: tuple[str, ...] = ("ok", "partial", "error", "disabled")


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_CASE_AREA = f"area IN ({quoted(AREAS)})"
CK_CASE_PRIORITY = f"priority IN ({quoted(PRIORITIES)})"
CK_CASE_STATUS = f"status IN ({quoted(STATUSES)})"
CK_CASE_SOURCE = f"source IN ({quoted(SOURCES)})"
CK_CASE_TITLE = "btrim(title) <> ''"
CK_CASE_CHECKLIST = "jsonb_typeof(checklist) = 'array'"
CK_CASE_CLOSED = f"(status IN ({quoted(TERMINAL_STATUSES)})) = (closed_at IS NOT NULL)"
CK_CASE_SOURCE_KEY = "source = 'manual' OR source_key IS NOT NULL"
CK_MESSAGE_ATTACHMENTS = "jsonb_typeof(attachments) = 'array'"
CK_COMMENT_BODY = "btrim(body) <> ''"
CK_STATE_SINGLETON = "id = 1"
CK_STATE_STATUS = f"last_status IS NULL OR last_status IN ({quoted(RUN_STATUSES)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS admin_cases (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    area VARCHAR(20) NOT NULL DEFAULT 'administration',
    priority VARCHAR(2) NOT NULL DEFAULT 'P2',
    status VARCHAR(16) NOT NULL DEFAULT 'new',
    due_on DATE NULL,
    follow_up_on DATE NULL,
    assignee_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    checklist JSONB NOT NULL DEFAULT '[]'::jsonb,
    description TEXT NULL,
    source VARCHAR(20) NOT NULL DEFAULT 'manual',
    source_key VARCHAR(200) NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    subject_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    lifecycle_case_id INTEGER NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at TIMESTAMPTZ NULL,
    CONSTRAINT uq_admin_cases_source_key UNIQUE (source_key),
    CONSTRAINT ck_admin_cases_area CHECK ({CK_CASE_AREA}),
    CONSTRAINT ck_admin_cases_priority CHECK ({CK_CASE_PRIORITY}),
    CONSTRAINT ck_admin_cases_status CHECK ({CK_CASE_STATUS}),
    CONSTRAINT ck_admin_cases_source CHECK ({CK_CASE_SOURCE}),
    CONSTRAINT ck_admin_cases_title CHECK ({CK_CASE_TITLE}),
    CONSTRAINT ck_admin_cases_checklist CHECK ({CK_CASE_CHECKLIST}),
    CONSTRAINT ck_admin_cases_closed CHECK ({CK_CASE_CLOSED}),
    CONSTRAINT ck_admin_cases_source_key CHECK ({CK_CASE_SOURCE_KEY})
)""",
    f"""CREATE TABLE IF NOT EXISTS admin_case_messages (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
    graph_message_id VARCHAR(512) NOT NULL,
    internet_message_id VARCHAR(512) NULL,
    conversation_id VARCHAR(512) NULL,
    sender_email VARCHAR(320) NULL,
    sender_name VARCHAR(200) NULL,
    subject VARCHAR(500) NULL,
    received_at TIMESTAMPTZ NULL,
    body_text TEXT NOT NULL DEFAULT '',
    attachments JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_admin_case_messages_graph UNIQUE (graph_message_id),
    CONSTRAINT ck_admin_case_messages_attachments CHECK ({CK_MESSAGE_ATTACHMENTS})
)""",
    f"""CREATE TABLE IF NOT EXISTS admin_case_comments (
    id SERIAL PRIMARY KEY,
    case_id INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
    author_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_admin_case_comments_body CHECK ({CK_COMMENT_BODY})
)""",
    f"""CREATE TABLE IF NOT EXISTS admin_mail_ingest_state (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    mailbox VARCHAR(320) NULL,
    last_received_at TIMESTAMPTZ NULL,
    last_run_started_at TIMESTAMPTZ NULL,
    last_run_finished_at TIMESTAMPTZ NULL,
    last_status VARCHAR(16) NULL,
    last_error TEXT NULL,
    stats JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_admin_mail_ingest_state_singleton CHECK ({CK_STATE_SINGLETON}),
    CONSTRAINT ck_admin_mail_ingest_state_status CHECK ({CK_STATE_STATUS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_admin_cases_status "
    "ON admin_cases (status, updated_at)",
    "CREATE INDEX IF NOT EXISTS ix_admin_cases_assignee "
    "ON admin_cases (assignee_user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_admin_cases_contract ON admin_cases (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_admin_cases_subject "
    "ON admin_cases (subject_user_id)",
    "CREATE INDEX IF NOT EXISTS ix_admin_case_messages_case "
    "ON admin_case_messages (case_id, received_at)",
    "CREATE INDEX IF NOT EXISTS ix_admin_case_messages_conversation "
    "ON admin_case_messages (conversation_id)",
    "CREATE INDEX IF NOT EXISTS ix_admin_case_messages_internet "
    "ON admin_case_messages (internet_message_id)",
    "CREATE INDEX IF NOT EXISTS ix_admin_case_comments_case "
    "ON admin_case_comments (case_id, created_at)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "admin_cases",
    "admin_case_messages",
    "admin_case_comments",
    "admin_mail_ingest_state",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
