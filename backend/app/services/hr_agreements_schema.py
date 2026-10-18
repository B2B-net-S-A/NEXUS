"""„Ludzie w NEXUSIE” — umowy z ludźmi (etap 5, E5): SQL migracji ``0470_hr_agreements`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0470_hr_agreements.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w pozostałych
``*_schema.py``; każda instrukcja idempotentna.

Umowy z osobami zespołu wszystkich form (B2B biura, zlecenie, UoP — tylko jako
dokument do podpisu — i aneksy) z wgrywanych wzorów, podpis przez Autenti
(albo ręcznie ze skanem) i przepisanie danych do kartoteki po podpisie.
Treści prawnej NEXUS nie pisze: wzory to pliki DOCX od Kadr z polami z listy
(``services/hr/agreements_templates.FIELDS``), wypełniane w sandboksie wzorów
protokołów sprzętu. PESEL-u ani numeru dowodu nie ma w żadnym polu —
tożsamość przy podpisie potwierdza Autenti.

Tabele:

* ``hr_agreement_templates`` — wzór: rodzaj (``b2b``, ``zlecenie``, ``uop``,
  ``annex``), nazwa, opis, w użyciu albo wycofany. Wzoru się nie kasuje.
* ``hr_agreement_template_versions`` — wersje pliku wzoru (1, 2, 3…): treść
  DOCX w bazie, skrót, użyte pola. Wersji się nie zmienia — nowy plik = nowa
  wersja; umowa wskazuje wersję, z której powstała, więc zawsze da się ją
  odtworzyć.
* ``hr_agreements`` — umowa albo aneks z osobą (``kind`` ``agreement`` /
  ``annex``), forma, stawka godzinowa z walutą, od–do, data zawarcia,
  potwierdzanie godzin (art. 8b — na zleceniu obowiązkowe), dzień wypłaty,
  koordynator. Stany:

  - ``draft`` — szkic: Kadry poprawiają pola, oglądają PDF; tu wraca umowa
    wycofana z Autenti albo po terminie podpisu (``last_error`` mówi czemu),
  - ``sent`` — wysłana do podpisu przez Autenti (``autenti_process_id``),
  - ``signed`` — podpisana: przez Autenti (plik podpisany pobrany, skrót
    w ``document_sha256``) albo ręcznie przez Kadry ze skanem, datą podpisu
    i powodem (``signing_channel = 'manual'``),
  - ``rejected`` — osoba odmówiła podpisu w Autenti,
  - ``cancelled`` — anulowana przez Kadry (z powodem).

  Najwyżej jedna umowa i jeden aneks w toku (szkic albo wysłane) na osobę.
  ``document_fields`` to wartości pól zamrożone przy wysyłce (dokument
  wysłany = dokument podpisany). Po podpisie, w jednej transakcji
  i idempotentnie (``applied_at``): stawka od daty w historii stawek, forma
  i potwierdzanie godzin w kartotece (aneks — tylko stawka), dokument
  w e-teczce (``document_id`` — dokument modułu dokumentów osoby) i znacznik
  ``symfonia_pending`` (UoP i zlecenie — nowa umowa do założenia w Symfonii
  przy najbliższym eksporcie; B2B do Symfonii nie idzie). Nieudane
  przepisanie po podpisie w Autenti zostawia umowę podpisaną z
  ``apply_error`` — „Przepisz ponownie” albo kolejny przebieg pętli.
"""

from __future__ import annotations

from app.services.hr_foundation_schema import EMPLOYMENT_TYPES
from app.services.hr_payroll_schema import CURRENCIES

#: Zmiana stanu umowy po stronie Autenti albo nieudane przepisanie do
#: kartoteki → osoba z Kadr, która wysłała umowę. Bez kwot w treści.
#: Wartość enuma dodaje migracja 0469; do ``PERSONAL_TYPES`` modułu
#: powiadomień dopina ją koordynator.
NOTIFICATION_TYPES: tuple[str, ...] = ("hr_agreement_update",)
ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)

TEMPLATE_KINDS: tuple[str, ...] = ("b2b", "zlecenie", "uop", "annex")
AGREEMENT_KINDS: tuple[str, ...] = ("agreement", "annex")
STATUSES: tuple[str, ...] = ("draft", "sent", "signed", "rejected", "cancelled")
#: Umowa „w toku” — jedna na osobę i rodzaj (indeks częściowy).
LIVE_STATUSES: tuple[str, ...] = ("draft", "sent")
SIGNING_CHANNELS: tuple[str, ...] = ("autenti", "manual")

RATE_MAX = "9999999.99"
NAME_MAX_LENGTH = 120
DESCRIPTION_MAX_LENGTH = 300
REASON_MAX_LENGTH = 500
ERROR_MAX_LENGTH = 500
#: Limit pliku wzoru (spakowanego) — ten sam co wzorów protokołów sprzętu.
TEMPLATE_MAX_BYTES = 2 * 1024 * 1024
SEND_ATTEMPTS_MAX = 1000


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


SHA256_PATTERN = "'^[0-9a-f]{64}$'"

CK_TEMPLATE_KIND = f"kind IN ({quoted(TEMPLATE_KINDS)})"
CK_TEMPLATE_NAME = f"char_length(btrim(name)) BETWEEN 1 AND {NAME_MAX_LENGTH}"

CK_VERSION_NUMBER = "version >= 1"
CK_VERSION_SIZE = f"file_size BETWEEN 1 AND {TEMPLATE_MAX_BYTES}"
CK_VERSION_SHA = f"file_sha256 ~ {SHA256_PATTERN}"
CK_VERSION_FIELDS = "jsonb_typeof(fields) = 'array'"

CK_AGREEMENT_KIND = f"kind IN ({quoted(AGREEMENT_KINDS)})"
CK_AGREEMENT_TYPE = f"employment_type IN ({quoted(EMPLOYMENT_TYPES)})"
CK_AGREEMENT_STATUS = f"status IN ({quoted(STATUSES)})"
CK_AGREEMENT_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_AGREEMENT_RATE = f"hourly_rate >= 0 AND hourly_rate <= {RATE_MAX}"
CK_AGREEMENT_DATES = "end_date IS NULL OR end_date >= start_date"
CK_AGREEMENT_PAYOUT_DAY = "payout_day IS NULL OR payout_day BETWEEN 1 AND 31"
#: Aneks może wskazywać zmienianą umowę z NEXUSA; umowa — nie.
CK_AGREEMENT_BASE = "kind = 'annex' OR base_agreement_id IS NULL"
#: Art. 8b ustawy o minimalnym wynagrodzeniu: na zleceniu strony potwierdzają
#: liczbę godzin — umowa zlecenia bez potwierdzania godzin nie powstaje.
CK_AGREEMENT_MANDATE_HOURS = (
    "kind = 'annex' OR employment_type <> 'zlecenie' OR hours_confirmation"
)
CK_AGREEMENT_CHANNEL = (
    f"signing_channel IS NULL OR signing_channel IN ({quoted(SIGNING_CHANNELS)})"
)
CK_AGREEMENT_SENT = (
    "status <> 'sent' OR (sent_at IS NOT NULL AND autenti_process_id IS NOT NULL "
    "AND signing_channel = 'autenti' AND sent_sha256 IS NOT NULL)"
)
CK_AGREEMENT_SIGNED = (
    "(status = 'signed') = (signed_at IS NOT NULL) AND (status <> 'signed' "
    "OR (signing_channel IS NOT NULL AND signed_on IS NOT NULL "
    "AND document_sha256 IS NOT NULL))"
)
#: Ręczne „Oznacz jako podpisaną” = kto, skan (skrót) i powód w śladzie.
CK_AGREEMENT_MANUAL = (
    "signing_channel IS DISTINCT FROM 'manual' OR (status = 'signed' "
    "AND signed_by IS NOT NULL "
    f"AND char_length(manual_reason) BETWEEN 1 AND {REASON_MAX_LENGTH})"
)
CK_AGREEMENT_REJECTED = "(status = 'rejected') = (rejected_at IS NOT NULL)"
CK_AGREEMENT_CANCELLED = (
    "(status = 'cancelled') = (cancelled_at IS NOT NULL) AND (status <> 'cancelled' "
    f"OR char_length(cancel_reason) BETWEEN 1 AND {REASON_MAX_LENGTH})"
)
#: Dokument wysłany = dokument podpisany: pola zamrożone od wysyłki.
CK_AGREEMENT_FIELDS = (
    "status IN ('draft', 'cancelled') OR jsonb_typeof(document_fields) = 'object'"
)
CK_AGREEMENT_APPLIED = "applied_at IS NULL OR status = 'signed'"
#: B2B do Symfonii nie idzie; znacznik dopiero po przepisaniu do kartoteki.
CK_AGREEMENT_SYMFONIA = (
    "(NOT symfonia_pending OR (employment_type <> 'b2b' AND applied_at IS NOT NULL)) "
    "AND (symfonia_exported_at IS NULL OR applied_at IS NOT NULL)"
)
CK_AGREEMENT_HASHES = (
    f"(sent_sha256 IS NULL OR sent_sha256 ~ {SHA256_PATTERN}) "
    f"AND (document_sha256 IS NULL OR document_sha256 ~ {SHA256_PATTERN})"
)
CK_AGREEMENT_ATTEMPTS = f"send_attempts BETWEEN 0 AND {SEND_ATTEMPTS_MAX}"
LIVE_AGREEMENT_WHERE = f"status IN ({quoted(LIVE_STATUSES)})"
AUTENTI_PROCESS_WHERE = "autenti_process_id IS NOT NULL"
SYMFONIA_PENDING_WHERE = "symfonia_pending"
TEMPLATE_ACTIVE_WHERE = "is_active"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS hr_agreement_templates (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    name VARCHAR({NAME_MAX_LENGTH}) NOT NULL,
    description VARCHAR({DESCRIPTION_MAX_LENGTH}) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hr_agreement_templates_kind CHECK ({CK_TEMPLATE_KIND}),
    CONSTRAINT ck_hr_agreement_templates_name CHECK ({CK_TEMPLATE_NAME})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_agreement_template_versions (
    id SERIAL PRIMARY KEY,
    template_id INTEGER NOT NULL REFERENCES hr_agreement_templates(id) ON DELETE RESTRICT,
    version INTEGER NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    content BYTEA NOT NULL,
    file_sha256 VARCHAR(64) NOT NULL,
    file_size INTEGER NOT NULL,
    fields JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_hr_agreement_template_versions_number UNIQUE (template_id, version),
    CONSTRAINT ck_hr_agreement_template_versions_number CHECK ({CK_VERSION_NUMBER}),
    CONSTRAINT ck_hr_agreement_template_versions_size CHECK ({CK_VERSION_SIZE}),
    CONSTRAINT ck_hr_agreement_template_versions_sha CHECK ({CK_VERSION_SHA}),
    CONSTRAINT ck_hr_agreement_template_versions_fields CHECK ({CK_VERSION_FIELDS})
)""",
    f"""CREATE TABLE IF NOT EXISTS hr_agreements (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    kind VARCHAR(16) NOT NULL,
    employment_type VARCHAR(16) NOT NULL,
    template_version_id INTEGER NOT NULL
        REFERENCES hr_agreement_template_versions(id) ON DELETE RESTRICT,
    base_agreement_id INTEGER NULL REFERENCES hr_agreements(id) ON DELETE RESTRICT,
    status VARCHAR(16) NOT NULL DEFAULT 'draft',
    hourly_rate NUMERIC(12,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    start_date DATE NOT NULL,
    end_date DATE NULL,
    agreement_date DATE NOT NULL,
    hours_confirmation BOOLEAN NOT NULL DEFAULT TRUE,
    payout_day SMALLINT NULL,
    coordinator_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    document_fields JSONB NULL,
    sent_sha256 VARCHAR(64) NULL,
    document_sha256 VARCHAR(64) NULL,
    signing_channel VARCHAR(16) NULL,
    autenti_process_id VARCHAR(64) NULL,
    send_attempts SMALLINT NOT NULL DEFAULT 0,
    signer_email VARCHAR(255) NULL,
    sent_at TIMESTAMPTZ NULL,
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    signed_at TIMESTAMPTZ NULL,
    signed_on DATE NULL,
    signed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    manual_reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    rejected_at TIMESTAMPTZ NULL,
    cancelled_at TIMESTAMPTZ NULL,
    cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancel_reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    last_error VARCHAR({ERROR_MAX_LENGTH}) NULL,
    applied_at TIMESTAMPTZ NULL,
    apply_error VARCHAR({ERROR_MAX_LENGTH}) NULL,
    document_id INTEGER NULL,
    symfonia_pending BOOLEAN NOT NULL DEFAULT FALSE,
    symfonia_exported_at TIMESTAMPTZ NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hr_agreements_kind CHECK ({CK_AGREEMENT_KIND}),
    CONSTRAINT ck_hr_agreements_type CHECK ({CK_AGREEMENT_TYPE}),
    CONSTRAINT ck_hr_agreements_status CHECK ({CK_AGREEMENT_STATUS}),
    CONSTRAINT ck_hr_agreements_currency CHECK ({CK_AGREEMENT_CURRENCY}),
    CONSTRAINT ck_hr_agreements_rate CHECK ({CK_AGREEMENT_RATE}),
    CONSTRAINT ck_hr_agreements_dates CHECK ({CK_AGREEMENT_DATES}),
    CONSTRAINT ck_hr_agreements_payout_day CHECK ({CK_AGREEMENT_PAYOUT_DAY}),
    CONSTRAINT ck_hr_agreements_base CHECK ({CK_AGREEMENT_BASE}),
    CONSTRAINT ck_hr_agreements_mandate_hours CHECK ({CK_AGREEMENT_MANDATE_HOURS}),
    CONSTRAINT ck_hr_agreements_channel CHECK ({CK_AGREEMENT_CHANNEL}),
    CONSTRAINT ck_hr_agreements_sent CHECK ({CK_AGREEMENT_SENT}),
    CONSTRAINT ck_hr_agreements_signed CHECK ({CK_AGREEMENT_SIGNED}),
    CONSTRAINT ck_hr_agreements_manual CHECK ({CK_AGREEMENT_MANUAL}),
    CONSTRAINT ck_hr_agreements_rejected CHECK ({CK_AGREEMENT_REJECTED}),
    CONSTRAINT ck_hr_agreements_cancelled CHECK ({CK_AGREEMENT_CANCELLED}),
    CONSTRAINT ck_hr_agreements_fields CHECK ({CK_AGREEMENT_FIELDS}),
    CONSTRAINT ck_hr_agreements_applied CHECK ({CK_AGREEMENT_APPLIED}),
    CONSTRAINT ck_hr_agreements_symfonia CHECK ({CK_AGREEMENT_SYMFONIA}),
    CONSTRAINT ck_hr_agreements_hashes CHECK ({CK_AGREEMENT_HASHES}),
    CONSTRAINT ck_hr_agreements_attempts CHECK ({CK_AGREEMENT_ATTEMPTS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_agreement_templates_active_name "
    f"ON hr_agreement_templates (kind, name) WHERE {TEMPLATE_ACTIVE_WHERE}",
    # Jedna umowa i jeden aneks w toku na osobę (szkic albo wysłane).
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_agreements_live "
    f"ON hr_agreements (user_id, kind) WHERE {LIVE_AGREEMENT_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_hr_agreements_autenti_process "
    f"ON hr_agreements (autenti_process_id) WHERE {AUTENTI_PROCESS_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_hr_agreements_user "
    "ON hr_agreements (user_id, created_at)",
    "CREATE INDEX IF NOT EXISTS ix_hr_agreements_status "
    "ON hr_agreements (status, applied_at)",
    "CREATE INDEX IF NOT EXISTS ix_hr_agreements_template_version "
    "ON hr_agreements (template_version_id)",
    "CREATE INDEX IF NOT EXISTS ix_hr_agreements_symfonia "
    f"ON hr_agreements (user_id) WHERE {SYMFONIA_PENDING_WHERE}",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = (
    "hr_agreement_templates",
    "hr_agreement_template_versions",
    "hr_agreements",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
