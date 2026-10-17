"""„Ludzie w NEXUSIE” — Rozliczenia zespołu: SQL migracji ``0467_hr_settlements`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0467_hr_settlements.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Etap 4 (R1–R12, 17.10.2026): faktury
B2B z KSeF, rozliczenie zlecenia z potwierdzenia godzin, dane UoP do Symfonii,
statusy płatności z wyciągu. NEXUS nie liczy podatków ani składek — kwoty
oczekiwane biorą się z zamrożonej linii płac (``payroll_lines``).

Kontrakt modułu jak w pozostałych ``*_schema.py`` (``TABLE_DDL, COLUMN_DDL,
INDEX_DDL, CONSTRAINT_DDL, DATA_DDL, TABLES, DOWNGRADE_DDL, ALL_DDL``). Każda
instrukcja idempotentna: entrypoint wykonuje je przy każdym starcie.

Tabele:

* ``employee_billing_details`` — dane do rozliczeń osoby (jedna na osobę):
  NIP (10 cyfr; sumę kontrolną sprawdza serwis), nazwa i status VAT z wykazu
  podatników (biała lista) z datą sprawdzenia, rachunek bankowy ZASZYFROWANY
  (``app/core/encryption.TokenCipher``) + ostatnie 4 cyfry do wyświetlania,
  źródło rachunku (``white_list`` — z wykazu, ``manual`` — wpisany, dla zlecenia
  i UoP) z identyfikatorem zapytania do wykazu, termin płatności faktur w dniach
  (domyślnie 14) i identyfikator osoby w Symfonii (GUID albo numer ewidencyjny
  — PESEL nie trafia do NEXUSA). Widzą: osoba, Kadry, Płace. Rachunku nie ma
  w logach, audycie ani komunikatach błędów.
* ``payroll_settlements`` — rozliczenie osoby za zamknięty miesiąc (osoba ×
  waluta, jak linia płac). Powstaje przy zamknięciu miesiąca; ponowne otwarcie
  anuluje nieopłacone (``cancelled``), opłacone zostają jako dowód. Kwota
  oczekiwana i jej podstawa: B2B — netto faktury (``net``), zlecenie i UoP —
  brutto (``gross``). Stany:

  - ``awaiting_document`` — B2B czeka na fakturę (z KSeF albo PDF dopięty
    ręcznie); zlecenie i UoP tego stanu nie mają,
  - ``mismatch`` — dokument niezgodny z kwotą oczekiwaną co do grosza albo
    rachunek spoza białej listy; wychodzi korektą (nowa faktura) albo
    „Uznaj różnicę” — powód + DRUGA osoba z Płac/Finansów/admina
    (``override_*``, CHECK: zatwierdzający ≠ wnioskujący),
  - ``ready`` — zgodne, czeka na zatwierdzenie do zapłaty,
  - ``approved`` — zatwierdzone do zapłaty (nikt nie zatwierdza sobie),
  - ``paid`` — opłacone (wyciąg, paczka przelewów albo ręcznie z powodem),
  - ``cancelled`` — miesiąc otwarty ponownie przed zapłatą.

  Termin: B2B = data nadania numeru KSeF + dni z danych osoby; zlecenie i UoP
  = dzień z ustawień Płac (domyślnie 10. następnego miesiąca).
* ``payroll_invoices`` — faktury od osób: z KSeF (numer KSeF unikalny, skrót
  XML) albo PDF dopięty ręcznie. Zapisujemy wyłącznie faktury od NIP-ów
  z ``employee_billing_details`` (pozostałe tylko liczy pobieranie, bez danych).
  Korekta wskazuje fakturę pierwotną; dopasowanie do rozliczenia po NIP
  i miesiącu (``period_year``/``period_month`` z pozycji albo daty sprzedaży).
* ``payroll_payments`` — zdarzenia płatności: wiersz paczki przelewów (opcja,
  domyślnie wyłączona), wiersz wyciągu (MT940/CAMT.053; ponowny import tego
  samego pliku nic nie dubluje) albo ręczne „opłacono” z powodem. Wiersz
  wyciągu bez dopasowania ma ``settlement_id`` NULL i stan ``unmatched``.
"""

from __future__ import annotations

EMPLOYMENT_TYPES: tuple[str, ...] = ("uop", "b2b", "zlecenie")
CURRENCIES: tuple[str, ...] = ("PLN", "EUR", "USD")
VAT_STATUSES: tuple[str, ...] = ("active", "exempt", "unregistered")
ACCOUNT_SOURCES: tuple[str, ...] = ("white_list", "manual")
AMOUNT_BASES: tuple[str, ...] = ("net", "gross")
SETTLEMENT_STATUSES: tuple[str, ...] = (
    "awaiting_document",
    "mismatch",
    "ready",
    "approved",
    "paid",
    "cancelled",
)
#: Rozliczenia „w toku” — jedno na osobę, miesiąc i walutę (indeks częściowy).
LIVE_SETTLEMENT_STATUSES: tuple[str, ...] = (
    "awaiting_document",
    "mismatch",
    "ready",
    "approved",
    "paid",
)
#: Co uznaje druga osoba: różnicę kwoty albo rachunek spoza białej listy.
OVERRIDE_KINDS: tuple[str, ...] = ("amount", "white_list")
PAID_SOURCES: tuple[str, ...] = ("statement", "transfer_batch", "manual")
INVOICE_SOURCES: tuple[str, ...] = ("ksef", "manual_pdf")
INVOICE_KINDS: tuple[str, ...] = ("original", "correction")
INVOICE_MATCH_STATUSES: tuple[str, ...] = ("unmatched", "matched", "ignored")
PAYMENT_KINDS: tuple[str, ...] = ("transfer_batch", "statement_line", "manual")
PAYMENT_MATCH_STATUSES: tuple[str, ...] = ("matched", "unmatched", "ignored")
BATCH_FORMATS: tuple[str, ...] = ("elixir", "csv")
STATEMENT_FORMATS: tuple[str, ...] = ("mt940", "camt053")

AMOUNT_MAX = "100000000"
REASON_MAX_LENGTH = 500
TITLE_MAX_LENGTH = 300
#: Numer KSeF: ``NIP-RRRRMMDD-XXXXXX-XXXXXX-XX`` (35 znaków) — z zapasem.
KSEF_NUMBER_MAX = 64
TERMS_MAX_DAYS = 90


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


CK_BILLING_NIP = "nip IS NULL OR nip ~ '^[0-9]{10}$'"
CK_BILLING_VAT_STATUS = f"vat_status IS NULL OR vat_status IN ({quoted(VAT_STATUSES)})"
CK_BILLING_ACCOUNT = (
    "(account_encrypted IS NULL AND account_last4 IS NULL AND account_source IS NULL) "
    "OR (account_encrypted IS NOT NULL AND account_last4 ~ '^[0-9]{4}$' "
    f"AND account_source IN ({quoted(ACCOUNT_SOURCES)}))"
)
CK_BILLING_WHITE_LIST = (
    "account_source IS DISTINCT FROM 'white_list' OR account_check_request_id IS NOT NULL"
)
CK_BILLING_TERMS = f"payment_terms_days BETWEEN 0 AND {TERMS_MAX_DAYS}"
CK_BILLING_SYMFONIA = "symfonia_id IS NULL OR char_length(symfonia_id) BETWEEN 1 AND 64"

CK_SETTLEMENT_TYPE = f"employment_type IN ({quoted(EMPLOYMENT_TYPES)})"
CK_SETTLEMENT_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_SETTLEMENT_STATUS = f"status IN ({quoted(SETTLEMENT_STATUSES)})"
CK_SETTLEMENT_BASIS = f"amount_basis IN ({quoted(AMOUNT_BASES)})"
CK_SETTLEMENT_AMOUNT = f"expected_amount >= 0 AND expected_amount <= {AMOUNT_MAX}"
#: Tylko B2B czeka na dokument od osoby.
CK_SETTLEMENT_AWAITING = "status <> 'awaiting_document' OR employment_type = 'b2b'"
CK_SETTLEMENT_OVERRIDE_KIND = (
    f"override_kind IS NULL OR override_kind IN ({quoted(OVERRIDE_KINDS)})"
)
CK_SETTLEMENT_OVERRIDE_REASON = (
    "override_requested_by IS NULL OR (override_kind IS NOT NULL "
    f"AND char_length(override_reason) BETWEEN 1 AND {REASON_MAX_LENGTH})"
)
#: „Uznaj różnicę” = dwie różne osoby.
CK_SETTLEMENT_OVERRIDE_TWO_PEOPLE = (
    "override_confirmed_by IS NULL OR (override_requested_by IS NOT NULL "
    "AND override_confirmed_by <> override_requested_by)"
)
CK_SETTLEMENT_NOT_SELF_APPROVED = "approved_by IS NULL OR approved_by <> user_id"
CK_SETTLEMENT_APPROVED = "(approved_by IS NULL) OR approved_at IS NOT NULL"
CK_SETTLEMENT_PAID = (
    "(status = 'paid') = (paid_at IS NOT NULL) "
    f"AND (paid_at IS NULL OR paid_source IN ({quoted(PAID_SOURCES)}))"
)
CK_SETTLEMENT_PAID_REASON = (
    "paid_source IS DISTINCT FROM 'manual' OR char_length(paid_reason) "
    f"BETWEEN 1 AND {REASON_MAX_LENGTH}"
)
CK_SETTLEMENT_CANCELLED = "status <> 'cancelled' OR cancelled_at IS NOT NULL"
LIVE_SETTLEMENT_WHERE = f"status IN ({quoted(LIVE_SETTLEMENT_STATUSES)})"

CK_INVOICE_SOURCE = f"source IN ({quoted(INVOICE_SOURCES)})"
CK_INVOICE_KSEF = (
    "source <> 'ksef' OR (ksef_number IS NOT NULL AND xml_sha256 IS NOT NULL)"
)
CK_INVOICE_PDF = "source <> 'manual_pdf' OR pdf_storage_key IS NOT NULL"
CK_INVOICE_SELLER_NIP = "seller_nip ~ '^[0-9]{10}$'"
CK_INVOICE_KIND = f"invoice_kind IN ({quoted(INVOICE_KINDS)})"
CK_INVOICE_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_INVOICE_AMOUNTS = (
    f"abs(net_amount) <= {AMOUNT_MAX} AND abs(vat_amount) <= {AMOUNT_MAX} "
    f"AND abs(gross_amount) <= {AMOUNT_MAX}"
)
CK_INVOICE_PERIOD = (
    "(period_year IS NULL) = (period_month IS NULL) AND (period_year IS NULL "
    "OR (period_year BETWEEN 2020 AND 2100 AND period_month BETWEEN 1 AND 12))"
)
CK_INVOICE_ITEMS = "jsonb_typeof(items) = 'array'"
CK_INVOICE_MATCH = f"match_status IN ({quoted(INVOICE_MATCH_STATUSES)})"
CK_INVOICE_MATCHED = "match_status <> 'matched' OR settlement_id IS NOT NULL"
CK_INVOICE_HASHES = (
    "(xml_sha256 IS NULL OR xml_sha256 ~ '^[0-9a-f]{64}$') "
    "AND (pdf_sha256 IS NULL OR pdf_sha256 ~ '^[0-9a-f]{64}$')"
)
KSEF_NUMBER_WHERE = "ksef_number IS NOT NULL"

CK_PAYMENT_KIND = f"kind IN ({quoted(PAYMENT_KINDS)})"
CK_PAYMENT_MATCH = f"match_status IN ({quoted(PAYMENT_MATCH_STATUSES)})"
CK_PAYMENT_MATCHED = "match_status <> 'matched' OR settlement_id IS NOT NULL"
CK_PAYMENT_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_PAYMENT_AMOUNT = f"abs(amount) <= {AMOUNT_MAX}"
CK_PAYMENT_BATCH = (
    "kind <> 'transfer_batch' OR (batch_key IS NOT NULL "
    f"AND batch_format IN ({quoted(BATCH_FORMATS)}))"
)
CK_PAYMENT_STATEMENT = (
    "kind <> 'statement_line' OR (statement_sha256 ~ '^[0-9a-f]{64}$' "
    f"AND statement_format IN ({quoted(STATEMENT_FORMATS)}) "
    "AND statement_line_ref IS NOT NULL)"
)
CK_PAYMENT_MANUAL = (
    "kind <> 'manual' OR (settlement_id IS NOT NULL "
    f"AND char_length(reason) BETWEEN 1 AND {REASON_MAX_LENGTH})"
)
CK_PAYMENT_TITLE = f"title IS NULL OR char_length(title) <= {TITLE_MAX_LENGTH}"
CK_PAYMENT_LAST4 = "counterparty_last4 IS NULL OR counterparty_last4 ~ '^[0-9]{4}$'"
STATEMENT_LINE_WHERE = "kind = 'statement_line'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS employee_billing_details (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    nip VARCHAR(10) NULL,
    registry_name VARCHAR(255) NULL,
    vat_status VARCHAR(16) NULL,
    vat_checked_at TIMESTAMPTZ NULL,
    account_encrypted TEXT NULL,
    account_last4 VARCHAR(4) NULL,
    account_source VARCHAR(16) NULL,
    account_check_request_id VARCHAR(64) NULL,
    account_checked_at TIMESTAMPTZ NULL,
    payment_terms_days SMALLINT NOT NULL DEFAULT 14,
    symfonia_id VARCHAR(64) NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_employee_billing_details_user UNIQUE (user_id),
    CONSTRAINT ck_employee_billing_details_nip CHECK ({CK_BILLING_NIP}),
    CONSTRAINT ck_employee_billing_details_vat_status CHECK ({CK_BILLING_VAT_STATUS}),
    CONSTRAINT ck_employee_billing_details_account CHECK ({CK_BILLING_ACCOUNT}),
    CONSTRAINT ck_employee_billing_details_white_list CHECK ({CK_BILLING_WHITE_LIST}),
    CONSTRAINT ck_employee_billing_details_terms CHECK ({CK_BILLING_TERMS}),
    CONSTRAINT ck_employee_billing_details_symfonia CHECK ({CK_BILLING_SYMFONIA})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_settlements (
    id SERIAL PRIMARY KEY,
    period_id INTEGER NOT NULL REFERENCES payroll_periods(id) ON DELETE RESTRICT,
    line_id BIGINT NULL REFERENCES payroll_lines(id) ON DELETE SET NULL,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    employment_type VARCHAR(16) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    expected_amount NUMERIC(14,2) NOT NULL,
    amount_basis VARCHAR(8) NOT NULL,
    status VARCHAR(20) NOT NULL,
    due_on DATE NULL,
    document_sha256 VARCHAR(64) NULL,
    discrepancy_amount NUMERIC(14,2) NULL,
    correction_requested_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    correction_requested_at TIMESTAMPTZ NULL,
    override_kind VARCHAR(16) NULL,
    override_reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    override_requested_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    override_requested_at TIMESTAMPTZ NULL,
    override_confirmed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    override_confirmed_at TIMESTAMPTZ NULL,
    approved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    approved_at TIMESTAMPTZ NULL,
    paid_at TIMESTAMPTZ NULL,
    paid_source VARCHAR(16) NULL,
    paid_amount NUMERIC(14,2) NULL,
    paid_reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    paid_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cancelled_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_settlements_type CHECK ({CK_SETTLEMENT_TYPE}),
    CONSTRAINT ck_payroll_settlements_currency CHECK ({CK_SETTLEMENT_CURRENCY}),
    CONSTRAINT ck_payroll_settlements_status CHECK ({CK_SETTLEMENT_STATUS}),
    CONSTRAINT ck_payroll_settlements_basis CHECK ({CK_SETTLEMENT_BASIS}),
    CONSTRAINT ck_payroll_settlements_amount CHECK ({CK_SETTLEMENT_AMOUNT}),
    CONSTRAINT ck_payroll_settlements_awaiting CHECK ({CK_SETTLEMENT_AWAITING}),
    CONSTRAINT ck_payroll_settlements_override_kind CHECK ({CK_SETTLEMENT_OVERRIDE_KIND}),
    CONSTRAINT ck_payroll_settlements_override_reason
        CHECK ({CK_SETTLEMENT_OVERRIDE_REASON}),
    CONSTRAINT ck_payroll_settlements_override_two_people
        CHECK ({CK_SETTLEMENT_OVERRIDE_TWO_PEOPLE}),
    CONSTRAINT ck_payroll_settlements_not_self_approved
        CHECK ({CK_SETTLEMENT_NOT_SELF_APPROVED}),
    CONSTRAINT ck_payroll_settlements_approved CHECK ({CK_SETTLEMENT_APPROVED}),
    CONSTRAINT ck_payroll_settlements_paid CHECK ({CK_SETTLEMENT_PAID}),
    CONSTRAINT ck_payroll_settlements_paid_reason CHECK ({CK_SETTLEMENT_PAID_REASON}),
    CONSTRAINT ck_payroll_settlements_cancelled CHECK ({CK_SETTLEMENT_CANCELLED})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_invoices (
    id SERIAL PRIMARY KEY,
    source VARCHAR(16) NOT NULL,
    ksef_number VARCHAR({KSEF_NUMBER_MAX}) NULL,
    ksef_acquired_at TIMESTAMPTZ NULL,
    seller_nip VARCHAR(10) NOT NULL,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    invoice_number VARCHAR(256) NOT NULL,
    invoice_kind VARCHAR(16) NOT NULL DEFAULT 'original',
    corrects_invoice_id INTEGER NULL REFERENCES payroll_invoices(id) ON DELETE SET NULL,
    corrected_ksef_number VARCHAR({KSEF_NUMBER_MAX}) NULL,
    issue_date DATE NOT NULL,
    sale_date DATE NULL,
    period_year SMALLINT NULL,
    period_month SMALLINT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    net_amount NUMERIC(14,2) NOT NULL,
    vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    gross_amount NUMERIC(14,2) NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    xml_sha256 VARCHAR(64) NULL,
    pdf_storage_key VARCHAR(512) NULL,
    pdf_sha256 VARCHAR(64) NULL,
    settlement_id INTEGER NULL REFERENCES payroll_settlements(id) ON DELETE SET NULL,
    match_status VARCHAR(16) NOT NULL DEFAULT 'unmatched',
    added_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_invoices_source CHECK ({CK_INVOICE_SOURCE}),
    CONSTRAINT ck_payroll_invoices_ksef CHECK ({CK_INVOICE_KSEF}),
    CONSTRAINT ck_payroll_invoices_pdf CHECK ({CK_INVOICE_PDF}),
    CONSTRAINT ck_payroll_invoices_seller_nip CHECK ({CK_INVOICE_SELLER_NIP}),
    CONSTRAINT ck_payroll_invoices_kind CHECK ({CK_INVOICE_KIND}),
    CONSTRAINT ck_payroll_invoices_currency CHECK ({CK_INVOICE_CURRENCY}),
    CONSTRAINT ck_payroll_invoices_amounts CHECK ({CK_INVOICE_AMOUNTS}),
    CONSTRAINT ck_payroll_invoices_period CHECK ({CK_INVOICE_PERIOD}),
    CONSTRAINT ck_payroll_invoices_items CHECK ({CK_INVOICE_ITEMS}),
    CONSTRAINT ck_payroll_invoices_match CHECK ({CK_INVOICE_MATCH}),
    CONSTRAINT ck_payroll_invoices_matched CHECK ({CK_INVOICE_MATCHED}),
    CONSTRAINT ck_payroll_invoices_hashes CHECK ({CK_INVOICE_HASHES})
)""",
    f"""CREATE TABLE IF NOT EXISTS payroll_payments (
    id BIGSERIAL PRIMARY KEY,
    kind VARCHAR(16) NOT NULL,
    settlement_id INTEGER NULL REFERENCES payroll_settlements(id) ON DELETE SET NULL,
    match_status VARCHAR(16) NOT NULL DEFAULT 'unmatched',
    amount NUMERIC(14,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    booked_on DATE NULL,
    title VARCHAR({TITLE_MAX_LENGTH}) NULL,
    counterparty_last4 VARCHAR(4) NULL,
    batch_key VARCHAR(64) NULL,
    batch_format VARCHAR(8) NULL,
    statement_sha256 VARCHAR(64) NULL,
    statement_format VARCHAR(8) NULL,
    statement_line_ref VARCHAR(64) NULL,
    reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_payroll_payments_kind CHECK ({CK_PAYMENT_KIND}),
    CONSTRAINT ck_payroll_payments_match CHECK ({CK_PAYMENT_MATCH}),
    CONSTRAINT ck_payroll_payments_matched CHECK ({CK_PAYMENT_MATCHED}),
    CONSTRAINT ck_payroll_payments_currency CHECK ({CK_PAYMENT_CURRENCY}),
    CONSTRAINT ck_payroll_payments_amount CHECK ({CK_PAYMENT_AMOUNT}),
    CONSTRAINT ck_payroll_payments_batch CHECK ({CK_PAYMENT_BATCH}),
    CONSTRAINT ck_payroll_payments_statement CHECK ({CK_PAYMENT_STATEMENT}),
    CONSTRAINT ck_payroll_payments_manual CHECK ({CK_PAYMENT_MANUAL}),
    CONSTRAINT ck_payroll_payments_title CHECK ({CK_PAYMENT_TITLE}),
    CONSTRAINT ck_payroll_payments_last4 CHECK ({CK_PAYMENT_LAST4})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_employee_billing_details_nip "
    "ON employee_billing_details (nip) WHERE nip IS NOT NULL",
    # Jedno rozliczenie w toku na osobę, miesiąc i walutę (anulowane nie blokują).
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_settlements_live "
    "ON payroll_settlements (period_id, user_id, currency) "
    f"WHERE {LIVE_SETTLEMENT_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_payroll_settlements_status "
    "ON payroll_settlements (status, due_on)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_settlements_user "
    "ON payroll_settlements (user_id, period_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_invoices_ksef_number "
    f"ON payroll_invoices (ksef_number) WHERE {KSEF_NUMBER_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_payroll_invoices_seller_period "
    "ON payroll_invoices (seller_nip, period_year, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_invoices_settlement "
    "ON payroll_invoices (settlement_id)",
    # Ponowny import tego samego wyciągu nic nie dubluje.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_payments_statement_line "
    "ON payroll_payments (statement_sha256, statement_line_ref) "
    f"WHERE {STATEMENT_LINE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_payroll_payments_settlement "
    "ON payroll_payments (settlement_id)",
    "CREATE INDEX IF NOT EXISTS ix_payroll_payments_batch "
    "ON payroll_payments (batch_key) WHERE batch_key IS NOT NULL",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = (
    "employee_billing_details",
    "payroll_settlements",
    "payroll_invoices",
    "payroll_payments",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
