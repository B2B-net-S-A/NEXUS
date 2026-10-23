"""„Ludzie w NEXUSIE” — rozliczenie zgód w Finansach: SQL migracji ``0486_approval_settlement`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0486_approval_settlement.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Etap 3 zgód (decyzje Artura 20.10.2026): zatwierdzony wydatek rozliczają
Finanse. Faktura z KSeF pasująca do zgody przypina się sama, „Rozliczone”
klika osoba z Finansów; premie poza umową widać w Finansach tylko jako sumę;
każda niedopasowana faktura kosztowa trafia do kolejki „Faktury bez zgody”,
chyba że sprzedawca jest na liście „stały koszt”; faktury kosztowe zapisujemy
z samych metadanych KSeF (bez pobierania XML-a — limit pobrań zostaje dla
faktur kontraktorów).

* ``approval_documents`` — dokument wydatku: faktura albo paragon wgrany do
  zgody (``upload``, plik w magazynie, odczyt kwoty i sprzedawcy przez AI
  jako podpowiedź) albo faktura kosztowa z KSeF (``ksef``, numer KSeF
  unikalny). Stan: ``pinned`` (przy zgodzie, do rozliczenia), ``settled``
  (Finanse rozliczyły), ``unmatched`` (kolejka „Faktury bez zgody”),
  ``fixed_cost`` (sprzedawca ze „stałych kosztów”), ``dismissed`` (Finanse
  zamknęły z notatką). Dopłata (faktura wyższa o więcej niż 10%) ma stan na
  dokumencie: ``pending`` → ``approved`` / ``rejected``.
* ``approval_fixed_cost_sellers`` — NIP-y sprzedawców, których faktury nie
  wymagają zgody (czynsz, księgowość, telefony).
* ``approval_requests`` dostaje rozliczenie: ``settlement_status``
  (``open`` → ``documented`` → ``settled``; ``expired`` po 30 dniach bez
  dokumentu; subskrypcja i wydatek cykliczny: ``active`` → ``ended``),
  ``expires_on``, kto rozliczył, znany NIP sprzedawcy (dopasowanie KSeF),
  klienta prezentu (Historia zdarzeń klienta) i odnowienie subskrypcji
  rocznej (``renews_on``, pytanie do opiekuna 30 dni wcześniej).

Dzwonki ``hr_approval_topup_requested`` (do zatwierdzającego)
i ``hr_subscription_renewal`` (do opiekuna subskrypcji).
"""

from __future__ import annotations

from app.services.hr_approvals_schema import quoted

DOCUMENT_SOURCES: tuple[str, ...] = ("upload", "ksef")
DOCUMENT_TYPES: tuple[str, ...] = ("invoice", "receipt")
DOCUMENT_STATUSES: tuple[str, ...] = (
    "pinned",
    "settled",
    "unmatched",
    "fixed_cost",
    "dismissed",
)
ATTACHED_STATUSES: tuple[str, ...] = ("pinned", "settled")
READ_STATUSES: tuple[str, ...] = ("read", "failed", "skipped")
TOPUP_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")
SETTLEMENT_STATUSES: tuple[str, ...] = (
    "open",
    "documented",
    "settled",
    "expired",
    "active",
    "ended",
)
#: Zgoda, do której można dołączyć dokument albo przypiąć fakturę.
OPEN_SETTLEMENT_STATUSES: tuple[str, ...] = ("open", "documented", "active")

#: Faktura wyższa od zgody o więcej niż tyle procent = prośba o dopłatę.
TOPUP_TOLERANCE_PERCENT = 10
#: Zgoda bez dokumentu wygasa po tylu dniach od zatwierdzenia.
EXPIRY_DAYS = 30
#: Pytanie o odnowienie rocznej subskrypcji tyle dni przed odnowieniem.
RENEWAL_NOTICE_DAYS = 30
#: Plik dokumentu wydatku: PDF albo zdjęcie do 10 MB.
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS_PER_REQUEST = 20
NOTE_MAX_LENGTH = 1000
SELLER_NAME_MAX_LENGTH = 256
INVOICE_NUMBER_MAX_LENGTH = 256

NOTIFICATION_TYPES: tuple[str, ...] = (
    "hr_approval_topup_requested",
    "hr_subscription_renewal",
)
ENUM_DDL: tuple[str, ...] = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)
#: Odczyt kwoty i sprzedawcy z faktury albo paragonu (rejestr ``ai_models``).
AI_FEATURE_KEY = "expense_document_read"
AI_ENUM_DDL = f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{AI_FEATURE_KEY}'"
AI_SEED_DDL = (
    "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
    f"SELECT '{AI_FEATURE_KEY}', TRUE, 0, NOW(), NOW() "
    "WHERE NOT EXISTS ("
    f"SELECT 1 FROM ai_features WHERE feature = '{AI_FEATURE_KEY}')"
)

CK_DOC_SOURCE = f"source IN ({quoted(DOCUMENT_SOURCES)})"
CK_DOC_TYPE = f"doc_type IN ({quoted(DOCUMENT_TYPES)})"
CK_DOC_STATUS = f"status IN ({quoted(DOCUMENT_STATUSES)})"
#: Faktura z KSeF ma numer KSeF i NIP sprzedawcy; wgrany dokument ma plik.
CK_DOC_ORIGIN = (
    "(source = 'ksef' AND ksef_number IS NOT NULL AND seller_nip IS NOT NULL "
    "AND gross_amount IS NOT NULL) "
    "OR (source = 'upload' AND file_path IS NOT NULL AND sha256 IS NOT NULL "
    "AND approval_request_id IS NOT NULL)"
)
#: Przy zgodzie są tylko dokumenty przypięte i rozliczone; kolejka ich nie ma.
CK_DOC_ATTACHED = (
    f"(status IN ({quoted(ATTACHED_STATUSES)}) AND approval_request_id IS NOT NULL) "
    f"OR (status NOT IN ({quoted(ATTACHED_STATUSES)}) AND approval_request_id IS NULL)"
)
CK_DOC_SELLER_NIP = "seller_nip IS NULL OR seller_nip ~ '^[0-9]{10}$'"
CK_DOC_CURRENCY = "currency ~ '^[A-Z]{3}$'"
CK_DOC_READ = f"read_status IS NULL OR read_status IN ({quoted(READ_STATUSES)})"
CK_DOC_TOPUP = (
    f"topup_status IS NULL OR (topup_status IN ({quoted(TOPUP_STATUSES)}) "
    "AND topup_amount IS NOT NULL AND topup_amount > 0 "
    "AND topup_requested_at IS NOT NULL)"
)
CK_DOC_TOPUP_DECIDED = (
    "topup_status IS DISTINCT FROM 'approved' AND topup_status IS DISTINCT FROM 'rejected' "
    "OR (topup_decided_by IS NOT NULL AND topup_decided_at IS NOT NULL)"
)
CK_DOC_SETTLED = (
    "status <> 'settled' OR (settled_by IS NOT NULL AND settled_at IS NOT NULL)"
)

CK_REQ_SETTLEMENT = (
    f"settlement_status IS NULL OR (settlement_status IN ({quoted(SETTLEMENT_STATUSES)}) "
    "AND status = 'approved' AND kind <> 'bonus')"
)
CK_REQ_CLIENT = "client_id IS NULL OR kind = 'gift'"
CK_REQ_SELLER_NIP = "seller_nip IS NULL OR seller_nip ~ '^[0-9]{10}$'"

DOCUMENTS_TABLE = f"""CREATE TABLE IF NOT EXISTS approval_documents (
    id SERIAL PRIMARY KEY,
    source VARCHAR(8) NOT NULL,
    doc_type VARCHAR(10) NOT NULL DEFAULT 'invoice',
    status VARCHAR(12) NOT NULL,
    approval_request_id INTEGER NULL REFERENCES approval_requests(id) ON DELETE SET NULL,
    match_reason VARCHAR(32) NULL,
    ksef_number VARCHAR(64) NULL,
    ksef_invoice_type VARCHAR(16) NULL,
    seller_nip VARCHAR(10) NULL,
    seller_name VARCHAR({SELLER_NAME_MAX_LENGTH}) NULL,
    invoice_number VARCHAR({INVOICE_NUMBER_MAX_LENGTH}) NULL,
    issue_date DATE NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    net_amount NUMERIC(14, 2) NULL,
    vat_amount NUMERIC(14, 2) NULL,
    gross_amount NUMERIC(14, 2) NULL,
    file_path VARCHAR(512) NULL,
    file_name VARCHAR(255) NULL,
    mime VARCHAR(100) NULL,
    size_bytes INTEGER NULL,
    sha256 VARCHAR(64) NULL,
    read_status VARCHAR(10) NULL,
    read_result JSONB NULL,
    topup_status VARCHAR(10) NULL,
    topup_amount NUMERIC(14, 2) NULL,
    topup_requested_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    topup_requested_at TIMESTAMPTZ NULL,
    topup_decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    topup_decided_at TIMESTAMPTZ NULL,
    topup_note TEXT NULL,
    settled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    settled_at TIMESTAMPTZ NULL,
    settle_note TEXT NULL,
    closed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    closed_at TIMESTAMPTZ NULL,
    close_note TEXT NULL,
    added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    fetched_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_approval_documents_source CHECK ({CK_DOC_SOURCE}),
    CONSTRAINT ck_approval_documents_type CHECK ({CK_DOC_TYPE}),
    CONSTRAINT ck_approval_documents_status CHECK ({CK_DOC_STATUS}),
    CONSTRAINT ck_approval_documents_origin CHECK ({CK_DOC_ORIGIN}),
    CONSTRAINT ck_approval_documents_attached CHECK ({CK_DOC_ATTACHED}),
    CONSTRAINT ck_approval_documents_seller_nip CHECK ({CK_DOC_SELLER_NIP}),
    CONSTRAINT ck_approval_documents_currency CHECK ({CK_DOC_CURRENCY}),
    CONSTRAINT ck_approval_documents_read CHECK ({CK_DOC_READ}),
    CONSTRAINT ck_approval_documents_topup CHECK ({CK_DOC_TOPUP}),
    CONSTRAINT ck_approval_documents_topup_decided CHECK ({CK_DOC_TOPUP_DECIDED}),
    CONSTRAINT ck_approval_documents_settled CHECK ({CK_DOC_SETTLED})
)"""

FIXED_SELLERS_TABLE = f"""CREATE TABLE IF NOT EXISTS approval_fixed_cost_sellers (
    seller_nip VARCHAR(10) PRIMARY KEY,
    seller_name VARCHAR({SELLER_NAME_MAX_LENGTH}) NULL,
    note TEXT NULL,
    added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_approval_fixed_cost_sellers_nip CHECK (seller_nip ~ '^[0-9]{{10}}$')
)"""

TABLE_DDL: tuple[str, ...] = (DOCUMENTS_TABLE, FIXED_SELLERS_TABLE)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS "
    "client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS seller_nip VARCHAR(10) NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS "
    "settlement_status VARCHAR(12) NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS expires_on DATE NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS "
    "settled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS renews_on DATE NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS renewal_asked_for DATE NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS "
    "renewal_confirmed_for DATE NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS ended_on DATE NULL",
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS "
    "ended_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
)

ATTACHED_WHERE = "approval_request_id IS NOT NULL"
QUEUE_WHERE = "status = 'unmatched'"
KSEF_WHERE = "ksef_number IS NOT NULL"
SHA_WHERE = "sha256 IS NOT NULL AND approval_request_id IS NOT NULL"
SETTLEMENT_WHERE = "settlement_status IS NOT NULL"

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_documents_ksef_number "
    f"ON approval_documents (ksef_number) WHERE {KSEF_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_approval_documents_request_file "
    f"ON approval_documents (approval_request_id, sha256) WHERE {SHA_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_approval_documents_request "
    f"ON approval_documents (approval_request_id) WHERE {ATTACHED_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_approval_documents_queue "
    f"ON approval_documents (issue_date) WHERE {QUEUE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_approval_documents_seller "
    "ON approval_documents (seller_nip)",
    "CREATE INDEX IF NOT EXISTS ix_approval_requests_settlement "
    f"ON approval_requests (settlement_status, kind) WHERE {SETTLEMENT_WHERE}",
)


def _constraint(name: str, check: str) -> str:
    return f"""DO $$ BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{name}') THEN
            ALTER TABLE approval_requests ADD CONSTRAINT {name} CHECK ({check});
        END IF;
    END $$"""


CONSTRAINT_DDL: tuple[str, ...] = (
    _constraint("ck_approval_requests_settlement", CK_REQ_SETTLEMENT),
    _constraint("ck_approval_requests_client", CK_REQ_CLIENT),
    _constraint("ck_approval_requests_seller_nip", CK_REQ_SELLER_NIP),
)

#: Zgody zatwierdzone przed etapem 3 dostają rozliczenie (wydatek raz = do
#: rozliczenia bez terminu — decyzja Artura 22.10.2026; cykliczny = w rejestrze
#: z terminem 30 dni od decyzji).
DATA_DDL: tuple[str, ...] = (
    "UPDATE approval_requests SET "
    "settlement_status = CASE WHEN recurrence = 'once' THEN 'open' ELSE 'active' END, "
    "expires_on = CASE WHEN recurrence = 'once' THEN NULL ELSE "
    f"(decided_at AT TIME ZONE 'Europe/Warsaw')::date + {EXPIRY_DAYS} END "
    "WHERE status = 'approved' AND kind <> 'bonus' AND settlement_status IS NULL",
)
TABLES: tuple[str, ...] = ("approval_documents", "approval_fixed_cost_sellers")
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS ck_approval_requests_settlement",
    "ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS ck_approval_requests_client",
    "ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS ck_approval_requests_seller_nip",
    "DROP INDEX IF EXISTS ix_approval_requests_settlement",
    *(
        f"ALTER TABLE approval_requests DROP COLUMN IF EXISTS {column}"
        for column in (
            "client_id",
            "seller_nip",
            "settlement_status",
            "expires_on",
            "settled_by",
            "settled_at",
            "renews_on",
            "renewal_asked_for",
            "renewal_confirmed_for",
            "ended_on",
            "ended_by",
        )
    ),
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
