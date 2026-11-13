"""Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4): SQL migracji ``0696_sales_invoice_issue`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0696_sales_invoice_issue.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Tabele:

* ``client_invoice_series`` — licznik numeracji: seria (``PL`` ``NNN/MM/RRRR``,
  ``UE`` ``NNN/MM/RRRR/UE``, ``ZAL`` ``ZAL/N/MM/RRRR``, ``KOR``
  ``KOR/N/MM/RRRR``) × miesiąc daty wystawienia → następny numer. Numer bierze
  się z tego wiersza pod blokadą (``SELECT … FOR UPDATE``) dopiero tuż przed
  wysyłką do KSeF, więc szkic nie zjada numeru. Finanse ustawiają „następny
  numer” na ekranie ustawień — przejście z eBI24 w połowie miesiąca
  kontynuuje numerację.
* ``client_issued_invoices`` — faktura wystawiana w NEXUSIE, od szkicu do
  przyjęcia w KSeF. Stany (``status``):

  - ``draft`` — szkic bez numeru; usunięcie nie zostawia śladu w numeracji,
  - ``sending`` — numer nadany, XML zapisany, trwa wysyłka (zostaje, gdy
    odpowiedź KSeF nie dała pewności — „Sprawdź status”),
  - ``sent`` — KSeF przyjął plik do przetwarzania, czeka na wynik,
  - ``accepted`` — przyjęta, ma numer KSeF; łączy się z wpisem
    ``client_sales_invoices`` (``sales_invoice_id``, ten sam numer KSeF —
    odczyt z KSeF nie robi duplikatu),
  - ``rejected`` — KSeF odrzucił fakturę (kod i powód), ``failed`` — wysyłka
    nie doszła do KSeF (limit, awaria). Obie zostają przy numerze: faktura
    nie weszła do obrotu, więc po poprawce idzie ponownie z tym samym numerem,
  - ``cancelled`` — odrzucona faktura wycofana, a jej numer nie był ostatni
    w serii: wiersz zostaje jako ślad niewykorzystanego numeru (powód
    w ``ksef_status_text``). Wycofanie ostatniego numeru cofa licznik serii
    i kasuje wiersz.

  Pozycje (``lines``) i stan przed korektą (``lines_before``) są w JSONB:
  ``name, consultant, quantity, unit, unit_price, vat_rate, net, order_id``.
  Nabywca (``buyer``) to migawka z klienta przy tworzeniu szkicu, edytowalna
  w szkicu. Kwoty liczone przy zapisie; w walucie obcej kurs NBP z dnia
  roboczego przed datą dostawy (``fx_rate``, ``fx_date``).

Widzi i wystawia: uprawnienie „Moduł Finanse”. Wysyłka do KSeF za
``KSEF_SALES_ISSUE_MODE`` (domyślnie ``off``).
"""

from __future__ import annotations

from app.services.client_sales_invoices_schema import (
    AMOUNT_MAX,
    CURRENCIES,
    KSEF_NUMBER_MAX,
    quoted,
)

SERIES: tuple[str, ...] = ("PL", "UE", "ZAL", "KOR")
INVOICE_TYPES: tuple[str, ...] = ("VAT", "KOR", "ZAL")
STATUSES: tuple[str, ...] = (
    "draft",
    "sending",
    "sent",
    "accepted",
    "rejected",
    "failed",
    "cancelled",
)
NUMBER_MAX = 999999
INVOICE_NUMBER_MAX = 64
ORDER_NUMBER_MAX = 256
NOTES_MAX = 1000
REASON_MAX = 256
STATUS_TEXT_MAX = 500
REF_MAX = 64

CK_SERIES_CODE = f"series_code IN ({quoted(SERIES)})"
CK_SERIES_PERIOD = "period_year BETWEEN 2020 AND 2100 AND period_month BETWEEN 1 AND 12"
CK_SERIES_NEXT = f"next_number BETWEEN 1 AND {NUMBER_MAX}"

CK_ISSUED_TYPE = f"invoice_type IN ({quoted(INVOICE_TYPES)})"
CK_ISSUED_SERIES = f"series_code IN ({quoted(SERIES)})"
CK_ISSUED_STATUS = f"status IN ({quoted(STATUSES)})"
CK_ISSUED_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_ISSUED_NUMBER = (
    "(number_seq IS NULL) = (invoice_number IS NULL) "
    "AND (number_seq IS NULL) = (number_year IS NULL) "
    "AND (number_year IS NULL) = (number_month IS NULL) "
    f"AND (number_seq IS NULL OR number_seq BETWEEN 1 AND {NUMBER_MAX})"
)
#: Szkic nie ma numeru, każdy inny stan ma.
CK_ISSUED_DRAFT = "(status = 'draft') = (number_seq IS NULL)"
CK_ISSUED_ACCEPTED = "status <> 'accepted' OR ksef_number IS NOT NULL"
CK_ISSUED_CORRECTION = "(invoice_type = 'KOR') = (corrects_id IS NOT NULL)"
CK_ISSUED_PERIOD = (
    "(period_year IS NULL) = (period_month IS NULL) "
    "AND (period_year IS NULL OR (period_year BETWEEN 2020 AND 2100 "
    "AND period_month BETWEEN 1 AND 12))"
)
CK_ISSUED_JSON = (
    "jsonb_typeof(lines) = 'array' AND jsonb_typeof(lines_before) = 'array' "
    "AND jsonb_typeof(buyer) = 'object' AND jsonb_typeof(history) = 'array'"
)
CK_ISSUED_AMOUNTS = (
    f"abs(net_amount) <= {AMOUNT_MAX} AND abs(vat_amount) <= {AMOUNT_MAX} "
    f"AND abs(gross_amount) <= {AMOUNT_MAX}"
)
NUMBERED_WHERE = "number_seq IS NOT NULL"
KSEF_WHERE = "ksef_number IS NOT NULL"
CORRECTS_WHERE = "corrects_id IS NOT NULL"
GROUP_WHERE = "order_group_id IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_invoice_series (
    series_code VARCHAR(8) NOT NULL,
    period_year SMALLINT NOT NULL,
    period_month SMALLINT NOT NULL,
    next_number INTEGER NOT NULL DEFAULT 1,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (series_code, period_year, period_month),
    CONSTRAINT ck_client_invoice_series_code CHECK ({CK_SERIES_CODE}),
    CONSTRAINT ck_client_invoice_series_period CHECK ({CK_SERIES_PERIOD}),
    CONSTRAINT ck_client_invoice_series_next CHECK ({CK_SERIES_NEXT})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_issued_invoices (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE RESTRICT,
    invoice_type VARCHAR(8) NOT NULL DEFAULT 'VAT',
    series_code VARCHAR(8) NOT NULL DEFAULT 'PL',
    status VARCHAR(12) NOT NULL DEFAULT 'draft',
    number_seq INTEGER NULL,
    number_year SMALLINT NULL,
    number_month SMALLINT NULL,
    invoice_number VARCHAR({INVOICE_NUMBER_MAX}) NULL,
    order_group_id INTEGER NULL REFERENCES client_order_groups(id) ON DELETE SET NULL,
    order_id INTEGER NULL REFERENCES client_orders(id) ON DELETE SET NULL,
    period_year SMALLINT NULL,
    period_month SMALLINT NULL,
    corrects_id INTEGER NULL REFERENCES client_issued_invoices(id) ON DELETE RESTRICT,
    correction_reason VARCHAR({REASON_MAX}) NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    issue_date DATE NOT NULL,
    sale_date DATE NULL,
    period_from DATE NULL,
    period_to DATE NULL,
    due_date DATE NULL,
    client_order_number VARCHAR({ORDER_NUMBER_MAX}) NULL,
    notes VARCHAR({NOTES_MAX}) NULL,
    buyer JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    lines_before JSONB NOT NULL DEFAULT '[]'::jsonb,
    net_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    vat_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    gross_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
    fx_rate NUMERIC(14,6) NULL,
    fx_date DATE NULL,
    xml TEXT NULL,
    xml_sha256 VARCHAR(64) NULL,
    ksef_environment VARCHAR(8) NULL,
    ksef_session_ref VARCHAR({REF_MAX}) NULL,
    ksef_invoice_ref VARCHAR({REF_MAX}) NULL,
    ksef_number VARCHAR({KSEF_NUMBER_MAX}) NULL,
    ksef_status_code INTEGER NULL,
    ksef_status_text VARCHAR({STATUS_TEXT_MAX}) NULL,
    ksef_acquired_at TIMESTAMPTZ NULL,
    upo_xml TEXT NULL,
    sales_invoice_id INTEGER NULL REFERENCES client_sales_invoices(id) ON DELETE SET NULL,
    history JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    sent_at TIMESTAMPTZ NULL,
    accepted_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_issued_invoices_type CHECK ({CK_ISSUED_TYPE}),
    CONSTRAINT ck_client_issued_invoices_series CHECK ({CK_ISSUED_SERIES}),
    CONSTRAINT ck_client_issued_invoices_status CHECK ({CK_ISSUED_STATUS}),
    CONSTRAINT ck_client_issued_invoices_currency CHECK ({CK_ISSUED_CURRENCY}),
    CONSTRAINT ck_client_issued_invoices_number CHECK ({CK_ISSUED_NUMBER}),
    CONSTRAINT ck_client_issued_invoices_draft CHECK ({CK_ISSUED_DRAFT}),
    CONSTRAINT ck_client_issued_invoices_accepted CHECK ({CK_ISSUED_ACCEPTED}),
    CONSTRAINT ck_client_issued_invoices_correction CHECK ({CK_ISSUED_CORRECTION}),
    CONSTRAINT ck_client_issued_invoices_period CHECK ({CK_ISSUED_PERIOD}),
    CONSTRAINT ck_client_issued_invoices_json CHECK ({CK_ISSUED_JSON}),
    CONSTRAINT ck_client_issued_invoices_amounts CHECK ({CK_ISSUED_AMOUNTS})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    # Jeden numer w serii i miesiącu — także przy wyścigu dwóch wysyłek.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_issued_invoices_number "
    "ON client_issued_invoices (series_code, number_year, number_month, number_seq) "
    f"WHERE {NUMBERED_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_issued_invoices_ksef_number "
    f"ON client_issued_invoices (ksef_number) WHERE {KSEF_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_client_issued_invoices_status "
    "ON client_issued_invoices (status, issue_date)",
    "CREATE INDEX IF NOT EXISTS ix_client_issued_invoices_client "
    "ON client_issued_invoices (client_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_issued_invoices_group_period "
    "ON client_issued_invoices (order_group_id, period_year, period_month) "
    f"WHERE {GROUP_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_client_issued_invoices_corrects "
    f"ON client_issued_invoices (corrects_id) WHERE {CORRECTS_WHERE}",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

TABLES: tuple[str, ...] = ("client_issued_invoices", "client_invoice_series")

DOWNGRADE_DDL: tuple[str, ...] = tuple(
    f"DROP TABLE IF EXISTS {table}" for table in TABLES
)
