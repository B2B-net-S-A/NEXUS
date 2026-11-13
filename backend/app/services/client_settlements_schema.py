"""Rozliczenia klientów, etap E1 (roadmapa ``docs/rozliczenia-klientow-roadmapa.md``):
SQL migracji ``0679_client_settlements`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0679_client_settlements.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``).

Tabele:

* ``client_settlements`` — rozliczenie osoby (kontrakt) za miesiąc: stan RCP,
  MD, kwoty, wynik kontroli. Wiersz powstaje przy pierwszej czynności Finansów
  albo odczycie RCP; „Brak RCP” to brak wiersza i brak dokumentu w miesiącu.
  ``kind = 'estimate'`` to estymacja (E5), osobny wiersz za ten sam miesiąc.
* ``client_settlement_rule_sets`` — wersje reguł klienta: katalog jest w kodzie
  (``services/client_settlements/rules_catalog.py``), tu tylko poziom
  i parametry per klucz od miesiąca ``effective_from``. Miesiąc rozlicza się
  według najnowszej wersji nie późniejszej niż on.
* ``client_settlement_integration_costs`` (E5.1) — koszty integracji konsultanta
  na koszt B2B (klient ich nie zwraca), reguła ``cl.integration_costs``: limit na
  konsultanta (kandydat, a bez niego kontrakt) na rok kalendarzowy miesiąca
  kosztu. ``status``: ``pending`` (wpisały Finanse, czeka na DL-a klienta),
  ``approved`` (zgoda DL-a — obniża marżę miesiąca), ``rejected``.
* ``client_contractor_invoices`` (E4) — faktury kontraktorów z KSeF (``Subject2``)
  z samych metadanych, przypięte do kontraktu i miesiąca rozliczenia.
  ``nip_state``: ``known`` (NIP z kontraktu), ``suggested`` (NIP nieznany,
  sprzedawca nazywa się jak osoba z kontraktu — czeka na Finanse), ``confirmed``
  (Finanse zatwierdziły NIP), ``rejected`` (to nie ta osoba).

Zejście MD przy przyjęciu RCP idzie przez ``upsert_consumption`` ze źródłem
``settlement`` — dlatego CHECK źródła w ``client_order_md_consumptions`` dostaje
trzecią wartość.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

KINDS: tuple[str, ...] = ("actual", "estimate")
#: ``missing`` nie ma wiersza; pozostałe stany zapisujemy.
STATUSES: tuple[str, ...] = (
    "checking",
    "ok",
    "warnings",
    "needs_fix",
    "no_md",
    "accepted",
)
MD_SOURCES: tuple[str, ...] = ("import", "manual", "settlement")

PERIOD_CHECK = "period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'"
FROM_CHECK = "effective_from ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'"
CK_KIND = f"kind IN ({quoted(KINDS)})"
CK_STATUS = f"status IN ({quoted(STATUSES)})"
CK_MD_SOURCE = f"source IN ({quoted(MD_SOURCES)})"
CK_RULES_OBJECT = "jsonb_typeof(rules) = 'object'"
CK_LINES_ARRAY = "jsonb_typeof(lines) = 'array'"
CK_CHECKS_ARRAY = "jsonb_typeof(checks) = 'array'"
FIX_REASON_MAX = 1_000
NIP_STATES: tuple[str, ...] = ("known", "suggested", "confirmed", "rejected")
CK_NIP_STATE = f"nip_state IN ({quoted(NIP_STATES)})"
SELLER_NAME_MAX = 255
INTEGRATION_STATUSES: tuple[str, ...] = ("pending", "approved", "rejected")
CK_INTEGRATION_STATUS = f"status IN ({quoted(INTEGRATION_STATUSES)})"
CK_INTEGRATION_AMOUNT = "amount > 0"
INTEGRATION_DESCRIPTION_MAX = 300
INVOICE_NUMBER_MAX = 256

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS client_settlements (
    id SERIAL PRIMARY KEY,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    period_month VARCHAR(7) NOT NULL,
    kind VARCHAR(8) NOT NULL DEFAULT 'actual',
    status VARCHAR(12) NOT NULL DEFAULT 'checking',
    report_document_id INTEGER NULL REFERENCES cp_documents(id) ON DELETE SET NULL,
    order_id INTEGER NULL REFERENCES client_orders(id) ON DELETE SET NULL,
    md_regular NUMERIC(10, 3) NULL,
    md_extra NUMERIC(10, 3) NULL,
    md_onboarding NUMERIC(10, 3) NULL,
    md_charged NUMERIC(10, 3) NULL,
    amount_cost NUMERIC(14, 2) NULL,
    amount_revenue NUMERIC(14, 2) NULL,
    lines JSONB NOT NULL DEFAULT '[]'::jsonb,
    checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    fix_reason VARCHAR({FIX_REASON_MAX}) NULL,
    accepted_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    accepted_at TIMESTAMPTZ NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_settlements_contract_month UNIQUE (contract_id, period_month, kind),
    CONSTRAINT ck_client_settlements_period CHECK ({PERIOD_CHECK}),
    CONSTRAINT ck_client_settlements_kind CHECK ({CK_KIND}),
    CONSTRAINT ck_client_settlements_status CHECK ({CK_STATUS}),
    CONSTRAINT ck_client_settlements_lines CHECK ({CK_LINES_ARRAY}),
    CONSTRAINT ck_client_settlements_checks CHECK ({CK_CHECKS_ARRAY})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_settlement_rule_sets (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    effective_from VARCHAR(7) NOT NULL,
    rules JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_settlement_rule_sets_from UNIQUE (client_id, effective_from),
    CONSTRAINT ck_client_settlement_rule_sets_from CHECK ({FROM_CHECK}),
    CONSTRAINT ck_client_settlement_rule_sets_rules CHECK ({CK_RULES_OBJECT})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_contractor_invoices (
    id SERIAL PRIMARY KEY,
    ksef_number VARCHAR(64) NOT NULL,
    seller_nip VARCHAR(10) NOT NULL,
    seller_name VARCHAR({SELLER_NAME_MAX}) NULL,
    buyer_nip VARCHAR(16) NULL,
    invoice_number VARCHAR({INVOICE_NUMBER_MAX}) NULL,
    invoice_type VARCHAR(16) NULL,
    issue_date DATE NULL,
    acquired_at TIMESTAMPTZ NULL,
    currency VARCHAR(3) NOT NULL DEFAULT 'PLN',
    net_amount NUMERIC(14, 2) NULL,
    vat_amount NUMERIC(14, 2) NULL,
    gross_amount NUMERIC(14, 2) NOT NULL,
    contract_id INTEGER NULL REFERENCES contracts(id) ON DELETE SET NULL,
    period_month VARCHAR(7) NULL,
    nip_state VARCHAR(10) NOT NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_client_contractor_invoices_ksef UNIQUE (ksef_number),
    CONSTRAINT ck_client_contractor_invoices_period CHECK (period_month IS NULL OR {PERIOD_CHECK}),
    CONSTRAINT ck_client_contractor_invoices_nip_state CHECK ({CK_NIP_STATE})
)""",
    f"""CREATE TABLE IF NOT EXISTS client_settlement_integration_costs (
    id SERIAL PRIMARY KEY,
    client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
    contract_id INTEGER NOT NULL REFERENCES contracts(id) ON DELETE CASCADE,
    period_month VARCHAR(7) NOT NULL,
    amount NUMERIC(12, 2) NOT NULL,
    description VARCHAR({INTEGRATION_DESCRIPTION_MAX}) NOT NULL,
    status VARCHAR(10) NOT NULL DEFAULT 'pending',
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    decided_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_client_settlement_integration_costs_period CHECK ({PERIOD_CHECK}),
    CONSTRAINT ck_client_settlement_integration_costs_status CHECK ({CK_INTEGRATION_STATUS}),
    CONSTRAINT ck_client_settlement_integration_costs_amount CHECK ({CK_INTEGRATION_AMOUNT})
)""",
)

MD_SOURCES_SETTLEMENT: tuple[str, ...] = ("rcp", "manual")
CK_SETTLEMENT_MD_SOURCE = (
    f"md_source IS NULL OR md_source IN ({quoted(MD_SOURCES_SETTLEMENT)})"
)

#: E2: skąd MD w rozliczeniu — odczyt RCP albo wpis Finansów (wpis wygrywa z odczytem).
COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE client_settlements ADD COLUMN IF NOT EXISTS md_source VARCHAR(8) NULL",
    f"""DO $$ BEGIN
    ALTER TABLE client_settlements ADD CONSTRAINT ck_client_settlements_md_source
        CHECK ({CK_SETTLEMENT_MD_SOURCE});
EXCEPTION WHEN duplicate_object THEN NULL;
END $$""",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_client_settlements_client_month "
    "ON client_settlements (client_id, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_client_settlements_order "
    "ON client_settlements (order_id) WHERE order_id IS NOT NULL",
    "CREATE INDEX IF NOT EXISTS ix_client_contractor_invoices_contract_month "
    "ON client_contractor_invoices (contract_id, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_client_contractor_invoices_seller "
    "ON client_contractor_invoices (seller_nip)",
    "CREATE INDEX IF NOT EXISTS ix_client_settlement_integration_costs_contract "
    "ON client_settlement_integration_costs (contract_id, period_month)",
    "CREATE INDEX IF NOT EXISTS ix_client_settlement_integration_costs_client "
    "ON client_settlement_integration_costs (client_id, period_month)",
)

#: 0687 (E5.1): koszty integracji — sama nowa tabela i jej indeksy.
INTEGRATION_DDL: tuple[str, ...] = (TABLE_DDL[-1], *INDEX_DDL[-2:])

#: Trzecie źródło zużycia MD. Warunek w DO, żeby entrypoint nie przebudowywał
#: CHECK-a przy każdym starcie (pełny skan tabeli pod blokadą).
CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_md_consumptions_source'
          AND pg_get_constraintdef(oid) LIKE '%settlement%'
    ) THEN
        ALTER TABLE client_order_md_consumptions
            DROP CONSTRAINT IF EXISTS ck_md_consumptions_source;
        ALTER TABLE client_order_md_consumptions
            ADD CONSTRAINT ck_md_consumptions_source CHECK ({CK_MD_SOURCE});
    END IF;
END $$""",
)

DATA_DDL: tuple[str, ...] = ()

TABLES: tuple[str, ...] = (
    "client_settlements",
    "client_settlement_rule_sets",
    "client_contractor_invoices",
    "client_settlement_integration_costs",
)

ALL_DDL: tuple[str, ...] = (*TABLE_DDL, *COLUMN_DDL, *INDEX_DDL, *CONSTRAINT_DDL)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DELETE FROM client_order_md_consumptions WHERE source = 'settlement'",
    "ALTER TABLE client_order_md_consumptions DROP CONSTRAINT IF EXISTS ck_md_consumptions_source",
    "ALTER TABLE client_order_md_consumptions ADD CONSTRAINT ck_md_consumptions_source "
    "CHECK (source IN ('import', 'manual'))",
)
