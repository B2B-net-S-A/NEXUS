"""Szablony faktur cyklicznych i faktura z ręki (E6): SQL migracji ``0708_sales_invoice_templates`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0708_sales_invoice_templates.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

* ``client_invoice_templates`` — szablon faktury „co miesiąc”: nabywca
  (migawka jak w szkicu), pozycje, waluta, seria. Rodzaj ``service`` (usługi
  bez zamówienia w NEXUSIE) albo ``benefit`` (refaktura pakietu sportowego,
  opieki medycznej do kontraktora — ``benefit``). Szablon nie wystawia faktury
  sam: Finanse tworzą z niego szkice za wybrany miesiąc, a szkic idzie zwykłą
  drogą E4 (numer przy wysyłce, KSeF). Nazwa pozycji może mieć ``{okres}``
  (np. „październik 2026”), ``{mm}`` i ``{rrrr}``.
* ``client_issued_invoices`` dostaje ``template_id`` (szkic z szablonu;
  unikalny indeks = jeden szkic szablonu na miesiąc, wycofana faktura się nie
  liczy), a ``client_id`` przestaje być obowiązkowy: faktura z ręki i z
  szablonu może iść do nabywcy spoza kartoteki klientów (kontraktor przy
  refakturze, firma bez klienta w NEXUSIE) — nabywcą jest migawka ``buyer``.

Decyzja Artura z 15.11.2026 po audycie eBI24: w październiku 2026 eBI24
wystawił 212 faktur bez zamówienia w NEXUSIE (155 refaktur benefitów).
"""

from __future__ import annotations

from app.services.client_invoice_issue_schema import NOTES_MAX
from app.services.client_sales_invoices_schema import (
    CURRENCIES,
    KSEF_NUMBER_MAX,
    quoted,
)

KINDS: tuple[str, ...] = ("service", "benefit")
BENEFITS: tuple[str, ...] = ("sport", "medical", "other")
SOURCES: tuple[str, ...] = ("manual", "ksef", "invoice")
TEMPLATE_SERIES: tuple[str, ...] = ("PL", "UE")
NAME_MAX = 255

CK_TEMPLATE_KIND = f"kind IN ({quoted(KINDS)})"
CK_TEMPLATE_BENEFIT = (
    f"(kind = 'benefit') = (benefit IS NOT NULL) "
    f"AND (benefit IS NULL OR benefit IN ({quoted(BENEFITS)}))"
)
CK_TEMPLATE_SOURCE = f"source IN ({quoted(SOURCES)})"
CK_TEMPLATE_SERIES = f"series_code IN ({quoted(TEMPLATE_SERIES)})"
CK_TEMPLATE_CURRENCY = f"currency IN ({quoted(CURRENCIES)})"
CK_TEMPLATE_JSON = "jsonb_typeof(lines) = 'array' AND jsonb_typeof(buyer) = 'object'"
CK_TEMPLATE_DAYS = "payment_days IS NULL OR payment_days BETWEEN 0 AND 180"
CK_TEMPLATE_VALID = "valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to"
TEMPLATE_PERIOD_WHERE = "template_id IS NOT NULL AND status <> 'cancelled'"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_invoice_templates (
    id SERIAL PRIMARY KEY,
    kind VARCHAR(8) NOT NULL DEFAULT 'service',
    benefit VARCHAR(8) NULL,
    name VARCHAR({NAME_MAX}) NOT NULL,
    active BOOLEAN NOT NULL DEFAULT true,
    client_id INTEGER NULL REFERENCES clients(id) ON DELETE SET NULL,
    buyer JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    series_code VARCHAR(8) NOT NULL DEFAULT 'PL',
    lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    payment_days SMALLINT NULL,
    notes VARCHAR({NOTES_MAX}) NULL,
    valid_from DATE NULL,
    valid_to DATE NULL,
    source VARCHAR(8) NOT NULL DEFAULT 'manual',
    source_ref VARCHAR({KSEF_NUMBER_MAX}) NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_invoice_templates_kind CHECK ({CK_TEMPLATE_KIND}),
    CONSTRAINT ck_client_invoice_templates_benefit CHECK ({CK_TEMPLATE_BENEFIT}),
    CONSTRAINT ck_client_invoice_templates_source CHECK ({CK_TEMPLATE_SOURCE}),
    CONSTRAINT ck_client_invoice_templates_series CHECK ({CK_TEMPLATE_SERIES}),
    CONSTRAINT ck_client_invoice_templates_currency CHECK ({CK_TEMPLATE_CURRENCY}),
    CONSTRAINT ck_client_invoice_templates_json CHECK ({CK_TEMPLATE_JSON}),
    CONSTRAINT ck_client_invoice_templates_days CHECK ({CK_TEMPLATE_DAYS}),
    CONSTRAINT ck_client_invoice_templates_valid CHECK ({CK_TEMPLATE_VALID})
)""",
)

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE client_issued_invoices ALTER COLUMN client_id DROP NOT NULL",
    "ALTER TABLE client_issued_invoices ADD COLUMN IF NOT EXISTS template_id "
    "INTEGER NULL REFERENCES client_invoice_templates(id) ON DELETE SET NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_invoice_templates_kind "
    "ON client_invoice_templates (kind, active)",
    # Jeden szkic szablonu na miesiąc — także przy dwóch kliknięciach naraz.
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_issued_invoices_template_period "
    "ON client_issued_invoices (template_id, period_year, period_month) "
    f"WHERE {TEMPLATE_PERIOD_WHERE}",
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

TABLES: tuple[str, ...] = ("client_invoice_templates",)

# Powrót: wiersze bez klienta (faktura z ręki do nabywcy spoza kartoteki) nie
# zmieszczą się w NOT NULL — downgrade ich nie kasuje, tylko odpada na SET NOT NULL.
DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_client_issued_invoices_template_period",
    "ALTER TABLE client_issued_invoices DROP COLUMN IF EXISTS template_id",
    "ALTER TABLE client_issued_invoices ALTER COLUMN client_id SET NOT NULL",
    "DROP TABLE IF EXISTS client_invoice_templates",
)
