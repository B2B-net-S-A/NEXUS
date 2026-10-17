"""„Ludzie w NEXUSIE” — komunikaty do konsultantów (O12): SQL migracji ``0465_care_announcements``.

JEDNO źródło instrukcji dla ``alembic/versions/0465_care_announcements.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w ``admin_cases_schema`` (``TABLE_DDL, COLUMN_DDL, INDEX_DDL,
CONSTRAINT_DDL, DATA_DDL, TABLES, DOWNGRADE_DDL, ALL_DDL``); każda instrukcja
idempotentna.

Tabele:

* ``care_announcements`` — komunikat: rodzaj (obowiązkowy / informacyjny),
  temat i treść z polami ``{imię}`` i ``{opiekun}``, grupa odbiorców (JSON),
  wersja treści i wersja sprawdzona wysyłką próbną, zatwierdzenie. CHECK
  pilnuje, że zatwierdzający nie jest autorem — także poza ścieżką API.
  ``code`` to losowa część znacznika w temacie (``[Komunikat 12/7F2A]``):
  odpowiedź z samym numerem nie przypnie się do cudzego komunikatu.
* ``care_announcement_recipients`` — lista odbiorców zamrożona przy wysłaniu
  do zatwierdzenia (zatwierdzający widzi dokładnie tę listę), z wykluczeniami
  (brak e-maila, wypisani z informacyjnych) i stanem wysyłki każdej osoby.
  Token wypisu jest tylko jako SHA-256 — surowy idzie wyłącznie w mailu.
  Usunięcie kandydata (RODO) kasuje jego wiersze.
* ``care_announcement_opt_outs`` — wypis z komunikatów informacyjnych
  (jeden wiersz na kandydata). Obowiązkowe idą do wszystkich z grupy.
* ``care_announcement_replies`` — sprawa administracja@ z odpowiedzią na
  komunikat albo z odbitym mailem (rozpoznana po znaczniku w temacie).

Przełącznik wysyłki leży w ``app_settings[SETTING_KEY]`` i domyślnie go nie
ma, czyli wysyłka do konsultantów jest wyłączona (pierwszą uruchamia Artur).
"""

from __future__ import annotations

KINDS: tuple[str, ...] = ("mandatory", "informational")
#: ``pending`` = czeka na zatwierdzenie, ``queued`` = w kolejce wysyłki,
#: ``sent`` = kolejka skończyła (także z błędami pojedynczych osób).
STATUSES: tuple[str, ...] = ("draft", "pending", "queued", "sent", "cancelled")
RECIPIENT_STATUSES: tuple[str, ...] = (
    "pending",
    "sending",
    "sent",
    "failed",
    # Graph mógł przyjąć mail (502/504, zerwane połączenie po wysłaniu) —
    # bez ponowienia, żeby nikt nie dostał komunikatu dwa razy.
    "uncertain",
    "bounced",
    "excluded_no_email",
    "excluded_opted_out",
    "cancelled",
)
REPLY_KINDS: tuple[str, ...] = ("reply", "bounce")

SETTING_KEY = "care_announcements"
SUBJECT_MAX = 200
BODY_MAX = 10_000


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_KIND = f"kind IN ({quoted(KINDS)})"
CK_STATUS = f"status IN ({quoted(STATUSES)})"
CK_SUBJECT = "btrim(subject) <> ''"
CK_BODY = f"btrim(body) <> '' AND length(body) <= {BODY_MAX}"
CK_CODE = "code ~ '^[A-Z0-9]{4,8}$'"
CK_AUDIENCE = "jsonb_typeof(audience) = 'object'"
CK_TESTED = "(tested_version IS NULL) = (tested_at IS NULL)"
CK_VERSIONS = "content_version >= 1 AND recipient_count >= 0"
#: Zatwierdzający nie może być autorem ani osobą, która wysłała komunikat
#: do zatwierdzenia (O12, cztery oczy).
CK_APPROVER = (
    "approved_by IS NULL OR ("
    "(created_by IS NULL OR approved_by <> created_by) AND "
    "(submitted_by IS NULL OR approved_by <> submitted_by))"
)
CK_APPROVED = "approved_by IS NULL OR approved_at IS NOT NULL"
CK_QUEUED = "status NOT IN ('queued', 'sent') OR queued_at IS NOT NULL"

CK_RECIPIENT_STATUS = f"status IN ({quoted(RECIPIENT_STATUSES)})"
CK_RECIPIENT_EMAIL = "status = 'excluded_no_email' OR email IS NOT NULL"
CK_RECIPIENT_SENT = "status NOT IN ('sent', 'bounced') OR sent_at IS NOT NULL"
CK_RECIPIENT_ATTEMPTS = "attempts >= 0"
CK_RECIPIENT_TOKEN = (
    "unsubscribe_token_sha256 IS NULL OR unsubscribe_token_sha256 ~ '^[0-9a-f]{64}$'"
)
CK_RECIPIENT_UNSUBSCRIBED = (
    "unsubscribed_at IS NULL OR unsubscribe_token_sha256 IS NOT NULL"
)
CK_REPLY_KIND = f"kind IN ({quoted(REPLY_KINDS)})"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS care_announcements (
    id SERIAL PRIMARY KEY,
    code VARCHAR(8) NOT NULL,
    kind VARCHAR(16) NOT NULL DEFAULT 'mandatory',
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    subject VARCHAR({SUBJECT_MAX}) NOT NULL,
    body TEXT NOT NULL,
    audience JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    content_version INTEGER NOT NULL DEFAULT 1,
    tested_version INTEGER NULL,
    tested_at TIMESTAMPTZ NULL,
    requires_approval BOOLEAN NOT NULL DEFAULT false,
    recipient_count INTEGER NOT NULL DEFAULT 0,
    return_note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    submitted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    submitted_at TIMESTAMPTZ NULL,
    approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ NULL,
    queued_at TIMESTAMPTZ NULL,
    send_started_at TIMESTAMPTZ NULL,
    send_finished_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_care_announcements_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_care_announcements_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_care_announcements_subject CHECK ({CK_SUBJECT}),
    CONSTRAINT ck_care_announcements_body CHECK ({CK_BODY}),
    CONSTRAINT ck_care_announcements_code CHECK ({CK_CODE}),
    CONSTRAINT ck_care_announcements_audience CHECK ({CK_AUDIENCE}),
    CONSTRAINT ck_care_announcements_tested CHECK ({CK_TESTED}),
    CONSTRAINT ck_care_announcements_versions CHECK ({CK_VERSIONS}),
    CONSTRAINT ck_care_announcements_approver CHECK ({CK_APPROVER}),
    CONSTRAINT ck_care_announcements_approved CHECK ({CK_APPROVED}),
    CONSTRAINT ck_care_announcements_queued CHECK ({CK_QUEUED})
)""",
    f"""CREATE TABLE IF NOT EXISTS care_announcement_recipients (
    id SERIAL PRIMARY KEY,
    announcement_id INTEGER NOT NULL
        REFERENCES care_announcements(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    owner_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    first_name VARCHAR(100) NULL,
    email VARCHAR(320) NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempts SMALLINT NOT NULL DEFAULT 0,
    error_code VARCHAR(40) NULL,
    simulated BOOLEAN NOT NULL DEFAULT false,
    claimed_at TIMESTAMPTZ NULL,
    sent_at TIMESTAMPTZ NULL,
    unsubscribe_token_sha256 VARCHAR(64) NULL,
    unsubscribed_at TIMESTAMPTZ NULL,
    bounced_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_care_announcement_recipients_person
        UNIQUE (announcement_id, candidate_id),
    CONSTRAINT uq_care_announcement_recipients_token
        UNIQUE (unsubscribe_token_sha256),
    CONSTRAINT ck_care_announcement_recipients_status CHECK ({CK_RECIPIENT_STATUS}),
    CONSTRAINT ck_care_announcement_recipients_email CHECK ({CK_RECIPIENT_EMAIL}),
    CONSTRAINT ck_care_announcement_recipients_sent CHECK ({CK_RECIPIENT_SENT}),
    CONSTRAINT ck_care_announcement_recipients_attempts
        CHECK ({CK_RECIPIENT_ATTEMPTS}),
    CONSTRAINT ck_care_announcement_recipients_token CHECK ({CK_RECIPIENT_TOKEN}),
    CONSTRAINT ck_care_announcement_recipients_unsubscribed
        CHECK ({CK_RECIPIENT_UNSUBSCRIBED})
)""",
    """CREATE TABLE IF NOT EXISTS care_announcement_opt_outs (
    candidate_id INTEGER PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE,
    recipient_id INTEGER NULL
        REFERENCES care_announcement_recipients(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)""",
    f"""CREATE TABLE IF NOT EXISTS care_announcement_replies (
    id SERIAL PRIMARY KEY,
    announcement_id INTEGER NOT NULL
        REFERENCES care_announcements(id) ON DELETE CASCADE,
    case_id INTEGER NOT NULL REFERENCES admin_cases(id) ON DELETE CASCADE,
    recipient_id INTEGER NULL
        REFERENCES care_announcement_recipients(id) ON DELETE SET NULL,
    kind VARCHAR(10) NOT NULL DEFAULT 'reply',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_care_announcement_replies_case UNIQUE (case_id),
    CONSTRAINT ck_care_announcement_replies_kind CHECK ({CK_REPLY_KIND})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_care_announcements_status "
    "ON care_announcements (status, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_care_announcements_author "
    "ON care_announcements (created_by)",
    "CREATE INDEX IF NOT EXISTS ix_care_announcement_recipients_queue "
    "ON care_announcement_recipients (status, announcement_id)",
    "CREATE INDEX IF NOT EXISTS ix_care_announcement_recipients_candidate "
    "ON care_announcement_recipients (candidate_id)",
    "CREATE INDEX IF NOT EXISTS ix_care_announcement_recipients_contract "
    "ON care_announcement_recipients (contract_id)",
    "CREATE INDEX IF NOT EXISTS ix_care_announcement_replies_announcement "
    "ON care_announcement_replies (announcement_id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "care_announcements",
    "care_announcement_recipients",
    "care_announcement_opt_outs",
    "care_announcement_replies",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
