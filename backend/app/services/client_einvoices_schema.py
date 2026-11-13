"""E-faktury Peppol do klientów (plan Nordei N2): SQL migracji ``0689_client_einvoices`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0689_client_einvoices.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Tabela ``client_sales_invoice_einvoices`` — jeden wiersz na fakturę sprzedażową
z KSeF (``client_sales_invoices``) do nabywcy, który ma adres w sieci Peppol
(odbiorcy w ``app_settings['peppol_einvoices']``, ``services/peppol/settings``):

* ``fa_xml`` — XML faktury z KSeF. ``client_sales_invoices`` trzyma tylko skrót;
  e-faktura potrzebuje pełnego pliku, więc zapisujemy go przy pobraniu z KSeF
  (bez dodatkowego zapytania), a brakujące doczytujemy z budżetu pętli
  sprzedaży (``xml_attempts``),
* ``status``: ``waiting_xml`` (czeka na XML z KSeF), ``waiting_receiver`` (podmiot
  bez adresu Peppol w danym trybie), ``invalid`` (konwersja albo reguły
  EN16931/Peppol nie przeszły — powód w ``problems``), ``ready`` (do wysłania),
  ``sent`` (przyjęta przez dostawcę, czeka na potwierdzenie), ``delivered``
  (punkt dostępu odbiorcy potwierdził), ``rejected`` (dostawca albo odbiorca
  odrzucił — powód w ``delivery_detail``), ``skipped`` (korekta bez zmiany
  kwot — nie ma czego wysłać),
* ``target`` — ``test`` (adres testowy odbiorcy) albo ``production``; wysyłka
  testowa nie zamyka faktury w trybie produkcyjnym,
* ``history`` — każda wysyłka (data, tryb, adres, identyfikator u dostawcy, wynik).

Samego UBL-a nie trzymamy: buduje się z ``fa_xml`` przy wysyłce i pobraniu
(z PDF-em), a ``ubl_sha256`` zapamiętuje skrót wysłanego pliku.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

STATUSES: tuple[str, ...] = (
    "waiting_xml",
    "waiting_receiver",
    "invalid",
    "ready",
    "sent",
    "delivered",
    "rejected",
    "skipped",
)
DOCUMENT_TYPES: tuple[str, ...] = ("invoice", "credit_note")
TARGETS: tuple[str, ...] = ("test", "production")
RECEIVER_KEY_MAX = 32
RECIPIENT_MAX = 64
PROVIDER_MAX = 16
PROVIDER_ID_MAX = 128
DETAIL_MAX = 500

CK_STATUS = f"status IN ({quoted(STATUSES)})"
CK_DOCUMENT_TYPE = f"document_type IS NULL OR document_type IN ({quoted(DOCUMENT_TYPES)})"
CK_TARGET = f"target IS NULL OR target IN ({quoted(TARGETS)})"
CK_SENT = "status NOT IN ('sent', 'delivered', 'rejected') OR sent_at IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_sales_invoice_einvoices (
    id SERIAL PRIMARY KEY,
    invoice_id INTEGER NOT NULL REFERENCES client_sales_invoices(id) ON DELETE CASCADE,
    receiver_key VARCHAR({RECEIVER_KEY_MAX}) NOT NULL,
    status VARCHAR(16) NOT NULL,
    document_type VARCHAR(12) NULL,
    fa_xml TEXT NULL,
    xml_attempts SMALLINT NOT NULL DEFAULT 0,
    problems JSONB NOT NULL DEFAULT '[]'::jsonb,
    target VARCHAR(10) NULL,
    recipient VARCHAR({RECIPIENT_MAX}) NULL,
    provider VARCHAR({PROVIDER_MAX}) NULL,
    provider_document_id VARCHAR({PROVIDER_ID_MAX}) NULL,
    delivery_detail VARCHAR({DETAIL_MAX}) NULL,
    ubl_sha256 VARCHAR(64) NULL,
    sent_at TIMESTAMPTZ NULL,
    sent_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    delivered_at TIMESTAMPTZ NULL,
    checked_at TIMESTAMPTZ NULL,
    history JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_sales_invoice_einvoices_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_client_sales_invoice_einvoices_document_type CHECK ({CK_DOCUMENT_TYPE}),
    CONSTRAINT ck_client_sales_invoice_einvoices_target CHECK ({CK_TARGET}),
    CONSTRAINT ck_client_sales_invoice_einvoices_sent CHECK ({CK_SENT})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoice_einvoices_invoice "
    "ON client_sales_invoice_einvoices (invoice_id)",
    "CREATE INDEX IF NOT EXISTS ix_client_sales_invoice_einvoices_status "
    "ON client_sales_invoice_einvoices (status)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

DATA_DDL: tuple[str, ...] = ()

DOWNGRADE_DDL: tuple[str, ...] = ("DROP TABLE IF EXISTS client_sales_invoice_einvoices",)
