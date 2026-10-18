"""Faktury sprzedażowe do klientów z KSeF (etap 5, E8 cz. 1): SQL migracji ``0470_client_sales_invoices`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0470_client_sales_invoices.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w pozostałych
``*_schema.py``; każda instrukcja idempotentna.

Decyzja E8 (17.10.2026): faktury do klientów wystawia się tam, gdzie dziś;
NEXUS liczy pozycje „do faktury” z zamówień (stawka × MD / godziny / okres),
czyta wystawione faktury z KSeF (spółka jako sprzedawca, ``Subject1``),
łączy je z zamówieniami, bierze zapłatę z uznań na wyciągu i pokazuje
zaległości Delivery Leadowi na jego klientach. Kwot „do faktury” nie
zapisujemy — liczą się przy odczycie z zamówień i zużycia MD, więc późniejszy
import MD od razu zmienia porównanie.

Tabele:

* ``client_sales_invoices`` — faktura z KSeF, w której spółka jest
  sprzedawcą (unikalny numer KSeF, skrót SHA-256 XML-a; samego XML-a nie
  trzymamy). Nabywca: NIP i nazwa z faktury, ``client_id`` — klient
  kanoniczny rozpoznany po NIP-ie (``clients.nip``, za scaleniem). Okres
  usługi: ``OkresFa/P_6_Do``, ``P_6`` albo wspólny miesiąc ``P_6A`` pozycji
  (``period_source='invoice'``); bez nich data wystawienia, bo brak ``P_6``
  w FA oznacza, że data sprzedaży jest równa dacie wystawienia
  (``issue_date``); Finanse mogą okres poprawić (``manual``). Termin
  płatności z ``Platnosc/TerminPlatnosci/Termin``; „Zapłacono” w samej
  fakturze — ``paid_in_invoice_on``. Korekta wskazuje fakturę pierwotną
  (``corrects_invoice_id``) i dziedziczy jej powiązania z zamówieniami.
  Dopasowanie (``match_status``):

  - ``unmatched`` — czeka na Finanse; ``match_reason`` mówi dlaczego
    (nieznany NIP nabywcy, kilka zamówień pasuje, kwota bez pewnego
    trafienia…) — system nie zgaduje,
  - ``matched`` — powiązana z zamówieniem albo zamówieniami
    (``client_sales_invoice_links``); ``match_method``: numer zamówienia
    w fakturze, jednoznaczna kwota, korekta pierwotnej albo ręcznie,
  - ``ignored`` — faktura spoza zamówień (np. sprzedaż sprzętu), z powodem.

  Różnicę między fakturą a „do faktury” Finanse mogą uznać z powodem
  (``difference_*``): uznanie dotyczy tej konkretnej różnicy — inna kwota
  po imporcie MD albo korekcie wraca do sprawdzenia.
* ``client_sales_invoice_links`` — powiązanie faktury z zamówieniem
  w miesiącu usługi: z całym zamówieniem klienta (``order_group_id`` — numer
  zamówienia MD/kosztowego z kilkoma osobami) albo z jednym zamówieniem
  (``order_id`` — zamówienie okresowe albo jedna osoba z zamówienia MD).
  Faktura na kilka zamówień ma kilka wierszy. Usunięcie zamówienia zabiera
  powiązanie (``CASCADE``), a faktura wraca do „do przypisania” przy odczycie.
* ``client_sales_invoice_payments`` — zapłata faktury: uznanie z wyciągu
  (MT940/CAMT.053 — ponowny import tego samego pliku nic nie dubluje) albo
  ręczne „opłacono” z powodem. Uznanie, które dotyczy faktury, ale bez
  pewnego dopasowania (kwota inna niż do zapłaty, kilka faktur pasuje), czeka
  jako ``unmatched`` na Finanse; uznania niezwiązane z fakturami (zwroty,
  odsetki) nie trafiają do bazy — liczymy je tylko.

Widzą: moduł Finanse (wszyscy klienci) i Delivery Lead u klientów ze swojego
portfela (reguła „DL widzi kwoty własnego portfela”); rekruter nie. Moduł za
przełącznikiem ``app_settings['client_invoicing']``, domyślnie wyłączony.
"""

from __future__ import annotations

INVOICE_KINDS: tuple[str, ...] = ("original", "correction")
CURRENCIES: tuple[str, ...] = ("PLN", "EUR", "USD")
PERIOD_SOURCES: tuple[str, ...] = ("invoice", "issue_date", "manual")
MATCH_STATUSES: tuple[str, ...] = ("unmatched", "matched", "ignored")
MATCH_METHODS: tuple[str, ...] = ("order_number", "amount", "correction", "manual")
PAYMENT_KINDS: tuple[str, ...] = ("statement_line", "manual")
PAYMENT_MATCH_STATUSES: tuple[str, ...] = ("matched", "unmatched", "ignored")
STATEMENT_FORMATS: tuple[str, ...] = ("mt940", "camt053")

AMOUNT_MAX = "100000000"
REASON_MAX_LENGTH = 500
TITLE_MAX_LENGTH = 300
COUNTERPARTY_MAX_LENGTH = 140
KSEF_NUMBER_MAX = 64
MATCH_REASON_MAX = 32


def quoted(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


_HEX64 = "'^[0-9a-f]{64}$'"


def _period(year: str, month: str) -> str:
    return f"{year} BETWEEN 2020 AND 2100 AND {month} BETWEEN 1 AND 12"


CK_INVOICE_KSEF_NUMBER = "ksef_number ~ '^[0-9]{10}-[0-9]{8}-[0-9A-F]{12}-[0-9A-F]{2}$'"
CK_INVOICE_XML_HASH = f"xml_sha256 ~ {_HEX64}"
CK_INVOICE_BUYER_NIP = "buyer_nip IS NULL OR buyer_nip ~ '^[0-9]{10}$'"
CK_INVOICE_KIND = f"invoice_kind IN ({quoted(INVOICE_KINDS)})"
CK_INVOICE_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_INVOICE_AMOUNTS = (
    f"abs(net_amount) <= {AMOUNT_MAX} AND abs(vat_amount) <= {AMOUNT_MAX} "
    f"AND abs(gross_amount) <= {AMOUNT_MAX}"
)
CK_INVOICE_PERIOD = (
    "(period_year IS NULL) = (period_month IS NULL) "
    "AND (period_year IS NULL) = (period_source IS NULL) "
    f"AND (period_year IS NULL OR ({_period('period_year', 'period_month')})) "
    f"AND (period_source IS NULL OR period_source IN ({quoted(PERIOD_SOURCES)}))"
)
CK_INVOICE_ITEMS = (
    "jsonb_typeof(items) = 'array' AND jsonb_typeof(order_refs) = 'array'"
)
CK_INVOICE_MATCH = f"match_status IN ({quoted(MATCH_STATUSES)})"
CK_INVOICE_METHOD = f"match_method IS NULL OR match_method IN ({quoted(MATCH_METHODS)})"
CK_INVOICE_MATCHED = "match_status <> 'matched' OR match_method IS NOT NULL"
CK_INVOICE_IGNORED = (
    "match_status <> 'ignored' OR char_length(ignore_reason) "
    f"BETWEEN 1 AND {REASON_MAX_LENGTH}"
)
CK_INVOICE_DIFFERENCE = (
    "difference_accepted_amount IS NULL OR (difference_accepted_by IS NOT NULL "
    "AND difference_accepted_at IS NOT NULL AND char_length(difference_reason) "
    f"BETWEEN 1 AND {REASON_MAX_LENGTH})"
)

CK_LINK_TARGET = "num_nonnulls(order_group_id, order_id) = 1"
CK_LINK_PERIOD = _period("period_year", "period_month")
LINK_GROUP_WHERE = "order_group_id IS NOT NULL"
LINK_ORDER_WHERE = "order_id IS NOT NULL"

CK_PAYMENT_KIND = f"kind IN ({quoted(PAYMENT_KINDS)})"
CK_PAYMENT_MATCH = f"match_status IN ({quoted(PAYMENT_MATCH_STATUSES)})"
CK_PAYMENT_MATCHED = "match_status <> 'matched' OR invoice_id IS NOT NULL"
CK_PAYMENT_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_PAYMENT_AMOUNT = f"amount > 0 AND amount <= {AMOUNT_MAX}"
CK_PAYMENT_STATEMENT = (
    f"kind <> 'statement_line' OR (statement_sha256 ~ {_HEX64} "
    f"AND statement_format IN ({quoted(STATEMENT_FORMATS)}) "
    "AND statement_line_ref IS NOT NULL)"
)
CK_PAYMENT_MANUAL = (
    "kind <> 'manual' OR (invoice_id IS NOT NULL AND booked_on IS NOT NULL "
    f"AND char_length(reason) BETWEEN 1 AND {REASON_MAX_LENGTH})"
)
CK_PAYMENT_IGNORED = (
    "match_status <> 'ignored' OR char_length(reason) "
    f"BETWEEN 1 AND {REASON_MAX_LENGTH}"
)
STATEMENT_LINE_WHERE = "kind = 'statement_line'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_sales_invoices (
    id SERIAL PRIMARY KEY,
    ksef_number VARCHAR({KSEF_NUMBER_MAX}) NOT NULL,
    ksef_acquired_at TIMESTAMPTZ NULL,
    xml_sha256 VARCHAR(64) NOT NULL,
    buyer_nip VARCHAR(10) NULL,
    buyer_name VARCHAR(255) NULL,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    invoice_number VARCHAR(256) NOT NULL,
    invoice_type VARCHAR(16) NOT NULL DEFAULT 'VAT',
    invoice_kind VARCHAR(16) NOT NULL DEFAULT 'original',
    corrects_invoice_id INTEGER NULL
        REFERENCES client_sales_invoices(id) ON DELETE SET NULL,
    corrected_ksef_number VARCHAR({KSEF_NUMBER_MAX}) NULL,
    corrected_invoice_number VARCHAR(256) NULL,
    issue_date DATE NOT NULL,
    sale_date DATE NULL,
    period_year SMALLINT NULL,
    period_month SMALLINT NULL,
    period_source VARCHAR(16) NULL,
    due_date DATE NULL,
    paid_in_invoice_on DATE NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    net_amount NUMERIC(14,2) NOT NULL,
    vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    gross_amount NUMERIC(14,2) NOT NULL,
    items JSONB NOT NULL DEFAULT '[]'::jsonb,
    order_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
    match_status VARCHAR(16) NOT NULL DEFAULT 'unmatched',
    match_method VARCHAR(16) NULL,
    match_reason VARCHAR({MATCH_REASON_MAX}) NULL,
    matched_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    matched_at TIMESTAMPTZ NULL,
    ignore_reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    difference_accepted_amount NUMERIC(14,2) NULL,
    difference_reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    difference_accepted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    difference_accepted_at TIMESTAMPTZ NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_sales_invoices_ksef_number CHECK ({CK_INVOICE_KSEF_NUMBER}),
    CONSTRAINT ck_client_sales_invoices_xml_hash CHECK ({CK_INVOICE_XML_HASH}),
    CONSTRAINT ck_client_sales_invoices_buyer_nip CHECK ({CK_INVOICE_BUYER_NIP}),
    CONSTRAINT ck_client_sales_invoices_kind CHECK ({CK_INVOICE_KIND}),
    CONSTRAINT ck_client_sales_invoices_currency CHECK ({CK_INVOICE_CURRENCY}),
    CONSTRAINT ck_client_sales_invoices_amounts CHECK ({CK_INVOICE_AMOUNTS}),
    CONSTRAINT ck_client_sales_invoices_period CHECK ({CK_INVOICE_PERIOD}),
    CONSTRAINT ck_client_sales_invoices_items CHECK ({CK_INVOICE_ITEMS}),
    CONSTRAINT ck_client_sales_invoices_match CHECK ({CK_INVOICE_MATCH}),
    CONSTRAINT ck_client_sales_invoices_method CHECK ({CK_INVOICE_METHOD}),
    CONSTRAINT ck_client_sales_invoices_matched CHECK ({CK_INVOICE_MATCHED}),
    CONSTRAINT ck_client_sales_invoices_ignored CHECK ({CK_INVOICE_IGNORED}),
    CONSTRAINT ck_client_sales_invoices_difference CHECK ({CK_INVOICE_DIFFERENCE})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_sales_invoice_links (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL
        REFERENCES client_sales_invoices(id) ON DELETE CASCADE,
    order_group_id INTEGER NULL
        REFERENCES client_order_groups(id) ON DELETE CASCADE,
    order_id INTEGER NULL REFERENCES client_orders(id) ON DELETE CASCADE,
    period_year SMALLINT NOT NULL,
    period_month SMALLINT NOT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_sales_invoice_links_target CHECK ({CK_LINK_TARGET}),
    CONSTRAINT ck_client_sales_invoice_links_period CHECK ({CK_LINK_PERIOD})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_sales_invoice_payments (
    id BIGSERIAL PRIMARY KEY,
    invoice_id INTEGER NULL REFERENCES client_sales_invoices(id) ON DELETE SET NULL,
    kind VARCHAR(16) NOT NULL,
    match_status VARCHAR(16) NOT NULL DEFAULT 'unmatched',
    amount NUMERIC(14,2) NOT NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    booked_on DATE NULL,
    title VARCHAR({TITLE_MAX_LENGTH}) NULL,
    counterparty_name VARCHAR({COUNTERPARTY_MAX_LENGTH}) NULL,
    statement_sha256 VARCHAR(64) NULL,
    statement_format VARCHAR(8) NULL,
    statement_line_ref VARCHAR(64) NULL,
    reason VARCHAR({REASON_MAX_LENGTH}) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    resolved_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_sales_invoice_payments_kind CHECK ({CK_PAYMENT_KIND}),
    CONSTRAINT ck_client_sales_invoice_payments_match CHECK ({CK_PAYMENT_MATCH}),
    CONSTRAINT ck_client_sales_invoice_payments_matched CHECK ({CK_PAYMENT_MATCHED}),
    CONSTRAINT ck_client_sales_invoice_payments_currency CHECK ({CK_PAYMENT_CURRENCY}),
    CONSTRAINT ck_client_sales_invoice_payments_amount CHECK ({CK_PAYMENT_AMOUNT}),
    CONSTRAINT ck_client_sales_invoice_payments_statement
        CHECK ({CK_PAYMENT_STATEMENT}),
    CONSTRAINT ck_client_sales_invoice_payments_manual CHECK ({CK_PAYMENT_MANUAL}),
    CONSTRAINT ck_client_sales_invoice_payments_ignored CHECK ({CK_PAYMENT_IGNORED})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoices_ksef_number "
    "ON client_sales_invoices (ksef_number)",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoices_client_period "
    "ON client_sales_invoices (client_id, period_year, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoices_match "
    "ON client_sales_invoices (match_status, issue_date)",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoices_corrects "
    "ON client_sales_invoices (corrects_invoice_id) "
    "WHERE corrects_invoice_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoices_buyer_nip "
    "ON client_sales_invoices (buyer_nip) WHERE buyer_nip IS NOT NULL",
    # Jedno powiązanie faktury z tym samym zamówieniem.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoice_links_group "
    "ON client_sales_invoice_links (invoice_id, order_group_id) "
    f"WHERE {LINK_GROUP_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoice_links_order "
    "ON client_sales_invoice_links (invoice_id, order_id) "
    f"WHERE {LINK_ORDER_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoice_links_group_period "
    "ON client_sales_invoice_links (order_group_id, period_year, period_month) "
    f"WHERE {LINK_GROUP_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoice_links_order_period "
    "ON client_sales_invoice_links (order_id, period_year, period_month) "
    f"WHERE {LINK_ORDER_WHERE}",
    # Ponowny import tego samego wyciągu nic nie dubluje.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoice_payments_statement "
    "ON client_sales_invoice_payments (statement_sha256, statement_line_ref) "
    f"WHERE {STATEMENT_LINE_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoice_payments_invoice "
    "ON client_sales_invoice_payments (invoice_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoice_payments_match "
    "ON client_sales_invoice_payments (match_status, booked_on)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = (
    "client_sales_invoices",
    "client_sales_invoice_links",
    "client_sales_invoice_payments",
)
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
