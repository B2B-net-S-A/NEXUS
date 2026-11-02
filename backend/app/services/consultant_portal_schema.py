"""Portal konsultanta (decyzje Artura 02.11.2026): SQL migracji ``0643_consultant_portal`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0643_consultant_portal.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu
jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Konsultant nie ma konta w NEXUSIE: wchodzi linkiem z maila, a finanse otwiera
kodem SMS. Wyłącznik ``app_settings['consultant_portal']`` jest domyślnie
wyłączony, więc kod wchodzi na produkcję ciemno.

Tabele:

* ``cp_links`` — jednorazowe linki z maila. W bazie wyłącznie SHA-256 tokenu.
  ``login`` otwiera sesję, ``rating`` przyjmuje ocenę jednej rozmowy.
* ``cp_sessions`` — sesja portalu, osobna od JWT pracownika: losowy token,
  w bazie hash, odwołanie działa od razu. ``sms_verified_until`` otwiera finanse.
* ``cp_sms_codes`` — kod SMS jako HMAC, z limitem prób i terminem.
* ``cp_faq_items`` — FAQ edytowany przez back office.
* ``cp_meetings`` — rezerwacje z portalu. Osobna tabela, bo ``prep_meetings``
  wymaga kandydata i rekrutacji. Częściowy unikat na (osoba, początek) zamyka
  podwójną rezerwację tego samego terminu.
* ``cp_ratings`` — ocena rozmowy. Ocena 1–2 zakłada zadanie dla kierownika
  (``followup_*``); osoba oceniana nie widzi pojedynczych ocen.
* ``cp_documents`` — raporty i faktury z dwóch kanałów: portal i ``rozliczenia@``.
  Ten sam plik z obu kanałów to jeden wiersz, a wszystkie wiersze okresu to jedna
  karta w kolumnie ``invoice`` zespołu ``finance``.
* ``cp_mailbox_state`` — jeden wiersz: znacznik czytnika ``rozliczenia@``.

Do ``admin_cases`` dochodzi źródło ``portal`` (blok ``DO``), wartość zna już też
``admin_cases_schema.SOURCES``.
"""

from __future__ import annotations

from app.services import admin_cases_schema

PORTAL_SETTING = "consultant_portal"
STATES: tuple[str, ...] = ("off", "pilot", "all")

LINK_PURPOSES: tuple[str, ...] = ("login", "rating")
#: Tematy portalu: FAQ, nowe zgłoszenie i rezerwacja rozmowy.
TOPICS: tuple[str, ...] = (
    "invoice",
    "contract",
    "leave",
    "access",
    "next",
    "data",
)
MEETING_STATUSES: tuple[str, ...] = ("pending", "booked", "cancelled", "failed")
TRANSCRIPT_STATUSES: tuple[str, ...] = (
    "waiting",
    "fetched",
    "missing",
    "forbidden",
    "error",
    "cancelled",
)
SUMMARY_STATUSES: tuple[str, ...] = ("pending", "done", "failed", "skipped")
FOLLOWUP_STATUSES: tuple[str, ...] = ("none", "open", "done")
DOCUMENT_KINDS: tuple[str, ...] = ("report", "invoice")
DOCUMENT_CHANNELS: tuple[str, ...] = ("portal", "mailbox")
DOCUMENT_STATUSES: tuple[str, ...] = ("received", "accepted", "rejected", "paid")
RUN_STATUSES: tuple[str, ...] = ("ok", "partial", "error", "disabled")

#: Dzwonek kierownika po ocenie 1–2 i przegląd miesięczny osoby. Do osobistych
#: typów modułu powiadomień dopina je ``hr_notification_schema``.
NOTIFICATION_TYPES: tuple[str, ...] = ("portal_low_rating", "portal_monthly_review")
AI_FEATURE_KEY = "portal_meeting_summary"
ENUM_DDL: tuple[str, ...] = (
    *(
        f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
        for value in NOTIFICATION_TYPES
    ),
    f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{AI_FEATURE_KEY}'",
)

QUESTION_MAX = 300
REASON_MAX = 1_000
COMMENT_MAX = 2_000
FILE_NAME_MAX = 255
MAX_SMS_ATTEMPTS = 5


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_LINK_PURPOSE = f"purpose IN ({quoted(LINK_PURPOSES)})"
CK_LINK_MEETING = "(purpose = 'rating') = (meeting_id IS NOT NULL)"
CK_SMS_ATTEMPTS = f"attempts >= 0 AND attempts <= {MAX_SMS_ATTEMPTS}"
CK_FAQ_TOPIC = f"topic IN ({quoted(TOPICS)})"
CK_FAQ_QUESTION = "btrim(question) <> ''"
CK_FAQ_ANSWER = "btrim(answer) <> ''"
CK_MEETING_TOPIC = f"topic IN ({quoted(TOPICS)})"
CK_MEETING_STATUS = f"status IN ({quoted(MEETING_STATUSES)})"
CK_MEETING_TRANSCRIPT = f"transcript_status IN ({quoted(TRANSCRIPT_STATUSES)})"
CK_MEETING_SUMMARY = f"summary_status IN ({quoted(SUMMARY_STATUSES)})"
CK_MEETING_SPAN = "end_at > start_at"
CK_MEETING_ITEMS = "jsonb_typeof(action_items) = 'array'"
CK_RATING_SCORE = "score >= 1 AND score <= 5"
CK_RATING_FOLLOWUP = f"followup_status IN ({quoted(FOLLOWUP_STATUSES)})"
CK_RATING_LOW = "(score <= 2) = (followup_status <> 'none')"
CK_DOCUMENT_KIND = f"kind IN ({quoted(DOCUMENT_KINDS)})"
CK_DOCUMENT_CHANNEL = f"channel IN ({quoted(DOCUMENT_CHANNELS)})"
CK_DOCUMENT_STATUS = f"status IN ({quoted(DOCUMENT_STATUSES)})"
CK_DOCUMENT_MONTH = "period_month >= 1 AND period_month <= 12"
CK_DOCUMENT_SIZE = "size_bytes > 0"
CK_STATE_SINGLETON = "id = 1"
CK_STATE_STATUS = f"last_status IS NULL OR last_status IN ({quoted(RUN_STATUSES)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS cp_meetings (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    host_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    case_id INTEGER NULL REFERENCES admin_cases(id) ON DELETE SET NULL,
    topic VARCHAR(12) NOT NULL,
    reason VARCHAR({REASON_MAX}) NOT NULL DEFAULT '',
    start_at TIMESTAMPTZ NOT NULL,
    end_at TIMESTAMPTZ NOT NULL,
    status VARCHAR(12) NOT NULL DEFAULT 'pending',
    client_request_id VARCHAR(64) NOT NULL,
    organizer_upn VARCHAR(320) NULL,
    graph_event_id VARCHAR(512) NULL,
    join_url TEXT NULL,
    organizer_aad_id VARCHAR(64) NULL,
    online_meeting_id VARCHAR(512) NULL,
    transcript_status VARCHAR(12) NOT NULL DEFAULT 'waiting',
    next_fetch_at TIMESTAMPTZ NULL,
    fetch_attempts INTEGER NOT NULL DEFAULT 0,
    last_error VARCHAR(200) NULL,
    transcript_text TEXT NULL,
    transcript_fetched_at TIMESTAMPTZ NULL,
    transcript_purged_at TIMESTAMPTZ NULL,
    summary TEXT NULL,
    action_items JSONB NOT NULL DEFAULT '[]'::jsonb,
    summary_status VARCHAR(12) NOT NULL DEFAULT 'pending',
    rating_requested_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cp_meetings_request UNIQUE (client_request_id),
    CONSTRAINT ck_cp_meetings_topic CHECK ({CK_MEETING_TOPIC}),
    CONSTRAINT ck_cp_meetings_status CHECK ({CK_MEETING_STATUS}),
    CONSTRAINT ck_cp_meetings_transcript CHECK ({CK_MEETING_TRANSCRIPT}),
    CONSTRAINT ck_cp_meetings_summary CHECK ({CK_MEETING_SUMMARY}),
    CONSTRAINT ck_cp_meetings_span CHECK ({CK_MEETING_SPAN}),
    CONSTRAINT ck_cp_meetings_items CHECK ({CK_MEETING_ITEMS})
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_links (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    purpose VARCHAR(8) NOT NULL DEFAULT 'login',
    meeting_id INTEGER NULL REFERENCES cp_meetings(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    used_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cp_links_token UNIQUE (token_hash),
    CONSTRAINT ck_cp_links_purpose CHECK ({CK_LINK_PURPOSE}),
    CONSTRAINT ck_cp_links_meeting CHECK ({CK_LINK_MEETING})
)""",
    """CREATE TABLE IF NOT EXISTS cp_sessions (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    email VARCHAR(255) NOT NULL,
    token_hash VARCHAR(64) NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ NULL,
    sms_verified_until TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cp_sessions_token UNIQUE (token_hash)
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_sms_codes (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES cp_sessions(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    code_hash VARCHAR(64) NOT NULL,
    attempts SMALLINT NOT NULL DEFAULT 0,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cp_sms_codes_attempts CHECK ({CK_SMS_ATTEMPTS})
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_faq_items (
    id SERIAL PRIMARY KEY,
    topic VARCHAR(12) NOT NULL,
    question VARCHAR({QUESTION_MAX}) NOT NULL,
    answer TEXT NOT NULL,
    position SMALLINT NOT NULL DEFAULT 0,
    published BOOLEAN NOT NULL DEFAULT TRUE,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cp_faq_items_topic CHECK ({CK_FAQ_TOPIC}),
    CONSTRAINT ck_cp_faq_items_question CHECK ({CK_FAQ_QUESTION}),
    CONSTRAINT ck_cp_faq_items_answer CHECK ({CK_FAQ_ANSWER})
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_ratings (
    id SERIAL PRIMARY KEY,
    meeting_id INTEGER NOT NULL REFERENCES cp_meetings(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    host_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    score SMALLINT NOT NULL,
    resolved BOOLEAN NULL,
    comment VARCHAR({COMMENT_MAX}) NULL,
    followup_status VARCHAR(8) NOT NULL DEFAULT 'none',
    followup_due_on DATE NULL,
    followup_note VARCHAR({COMMENT_MAX}) NULL,
    followup_done_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    followup_done_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_cp_ratings_meeting UNIQUE (meeting_id),
    CONSTRAINT ck_cp_ratings_score CHECK ({CK_RATING_SCORE}),
    CONSTRAINT ck_cp_ratings_followup CHECK ({CK_RATING_FOLLOWUP}),
    CONSTRAINT ck_cp_ratings_low CHECK ({CK_RATING_LOW})
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_documents (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    kind VARCHAR(8) NOT NULL,
    period_year SMALLINT NOT NULL,
    period_month SMALLINT NOT NULL,
    period_guessed BOOLEAN NOT NULL DEFAULT FALSE,
    channel VARCHAR(8) NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'received',
    file_path VARCHAR(500) NOT NULL,
    file_name VARCHAR({FILE_NAME_MAX}) NULL,
    mime VARCHAR(120) NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 VARCHAR(64) NOT NULL,
    graph_message_id VARCHAR(512) NULL,
    sender_email VARCHAR(320) NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    reject_reason VARCHAR({COMMENT_MAX}) NULL,
    invoice_signal_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_cp_documents_kind CHECK ({CK_DOCUMENT_KIND}),
    CONSTRAINT ck_cp_documents_channel CHECK ({CK_DOCUMENT_CHANNEL}),
    CONSTRAINT ck_cp_documents_status CHECK ({CK_DOCUMENT_STATUS}),
    CONSTRAINT ck_cp_documents_month CHECK ({CK_DOCUMENT_MONTH}),
    CONSTRAINT ck_cp_documents_size CHECK ({CK_DOCUMENT_SIZE})
)""",
    f"""CREATE TABLE IF NOT EXISTS cp_mailbox_state (
    id SMALLINT PRIMARY KEY DEFAULT 1,
    last_seen_received_at TIMESTAMPTZ NULL,
    last_run_at TIMESTAMPTZ NULL,
    last_status VARCHAR(10) NULL,
    last_error VARCHAR(500) NULL,
    CONSTRAINT ck_cp_mailbox_state_singleton CHECK ({CK_STATE_SINGLETON}),
    CONSTRAINT ck_cp_mailbox_state_status CHECK ({CK_STATE_STATUS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_cp_links_contract "
    "ON cp_links (contract_id, purpose, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_cp_sessions_contract ON cp_sessions (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_cp_sms_codes_contract "
    "ON cp_sms_codes (contract_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_cp_sms_codes_session ON cp_sms_codes (session_id)",
    "CREATE INDEX IF NOT EXISTS ix_cp_faq_items_topic "
    "ON cp_faq_items (topic, position)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cp_meetings_host_slot "
    "ON cp_meetings (host_user_id, start_at) "
    "WHERE status IN ('pending', 'booked')",
    "CREATE INDEX IF NOT EXISTS ix_cp_meetings_contract "
    "ON cp_meetings (contract_id, start_at)",
    "CREATE INDEX IF NOT EXISTS ix_cp_meetings_fetch "
    "ON cp_meetings (next_fetch_at) WHERE next_fetch_at IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_cp_ratings_host "
    "ON cp_ratings (host_user_id, created_at)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cp_documents_file "
    "ON cp_documents (contract_id, kind, period_year, period_month, sha256) "
    "WHERE contract_id IS NOT NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_cp_documents_mail_file "
    "ON cp_documents (graph_message_id, sha256) WHERE graph_message_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_cp_documents_contract "
    "ON cp_documents (contract_id, period_year, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_cp_documents_status ON cp_documents (status)",
)

#: Podmienia CHECK tylko przy starej definicji; na świeżej bazie 0463 ma już
#: pełną listę z ``admin_cases_schema.SOURCES`` i blok niczego nie robi.
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
    BEGIN
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'ck_admin_cases_source'
              AND conrelid = 'admin_cases'::regclass
              AND pg_get_constraintdef(oid) NOT LIKE '%portal%'
        ) THEN
            ALTER TABLE admin_cases DROP CONSTRAINT ck_admin_cases_source;
            ALTER TABLE admin_cases ADD CONSTRAINT ck_admin_cases_source
                CHECK ({admin_cases_schema.CK_CASE_SOURCE});
        END IF;
    END $$""",
)

DATA_DDL: tuple[str, ...] = (
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    f"SELECT '{AI_FEATURE_KEY}', TRUE, 0, now(), now() "
    "WHERE NOT EXISTS "
    f"(SELECT 1 FROM ai_features WHERE feature = '{AI_FEATURE_KEY}')",
)

TABLES: tuple[str, ...] = (
    "cp_meetings",
    "cp_links",
    "cp_sessions",
    "cp_sms_codes",
    "cp_faq_items",
    "cp_ratings",
    "cp_documents",
    "cp_mailbox_state",
)
DOWNGRADE_DDL: tuple[str, ...] = (
    "DELETE FROM admin_cases WHERE source = 'portal'",
    "ALTER TABLE admin_cases DROP CONSTRAINT IF EXISTS ck_admin_cases_source",
    "ALTER TABLE admin_cases ADD CONSTRAINT ck_admin_cases_source CHECK "
    "(source IN ('manual', 'mail', 'contract', 'lifecycle', 'compass_import'))",
    f"DELETE FROM ai_features WHERE feature = '{AI_FEATURE_KEY}'",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
