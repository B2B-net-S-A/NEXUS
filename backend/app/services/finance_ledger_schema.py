"""Księgowość w Finansach (E0, E1): SQL migracji ``0695_finance_ledger`` i lustra entrypointu.

Jedno źródło instrukcji dla ``alembic/versions/0695_finance_ledger.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

* ``finance_counterparties`` — kartoteka kontrahentów z kontami Symfonii
  (import z eBI24 „Partnerzy → Pobierz” i ręczna edycja). Identyfikator to typ
  (NIP, PESEL, VAT UE, inny) i wartość po normalizacji, unikalne razem; wiersz
  bez identyfikatora musi mieć ID partnera w Symfonii (też unikalne).
* ``finance_cost_entries`` — warstwa księgowa nad trzema źródłami faktur
  kosztowych: faktury osób zespołu (``payroll_invoices``), faktury kontraktorów
  klientów (``client_contractor_invoices``) i dokumenty wydatków
  (``approval_documents``). Klucz źródła (typ + id) jest unikalny; danych
  faktury nie kopiujemy (czyta je kolejka), poza NIP-em sprzedawcy i chwilą
  wpływu, które się nie zmieniają. Etap: ``received`` (poczekalnia KSeF) →
  ``new`` → ``verified`` → ``ready`` → ``booked`` (E2), obok ``rejected``.
* ``finance_cost_entry_events`` — historia zmian etapu, flag, kategorii
  i notatki (kto, kiedy, skąd, dokąd).

``ENTRY_INSERTS`` zakłada wpisy brakującym fakturom źródeł. Wykonuje je
migracja (backfill), entrypoint przy każdym starcie i przebieg KSeF na końcu
(``ledger.catch_up``); wstawia tylko faktury bez wpisu (``NOT EXISTS``),
a wpis istniejący zostaje bez zmian (``ON CONFLICT`` jako zabezpieczenie).
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted

STAGES: tuple[str, ...] = ("received", "new", "verified", "ready", "booked", "rejected")
FLAGS: tuple[str, ...] = (
    "mpp",
    "no_mpp",
    "hold_payment",
    "tax_office_account",
    "duplicate",
)
CATEGORIES: tuple[str, ...] = (
    "contractor",
    "team",
    "office",
    "benefit",
    "proforma",
    "other",
)
SOURCE_TYPES: tuple[str, ...] = (
    "payroll_invoice",
    "contractor_invoice",
    "approval_document",
)
ID_TYPES: tuple[str, ...] = ("nip", "pesel", "vat_eu", "other")
EVENT_ACTIONS: tuple[str, ...] = (
    "accept",
    "reject",
    "verify",
    "ready",
    "back",
    "flags",
    "category",
    "note",
    "due_date",
)

NAME_MAX = 255
ID_VALUE_MAX = 32
ACCOUNT_MAX = 32
SYMFONIA_ID_MAX = 32
REASON_MAX = 500

CK_ID_TYPE = f"id_type IS NULL OR id_type IN ({quoted(ID_TYPES)})"
CK_ID_PAIR = "(id_type IS NULL) = (id_value IS NULL)"
CK_KEY = "id_value IS NOT NULL OR symfonia_partner_id IS NOT NULL"
CK_SOURCE_TYPE = f"source_type IN ({quoted(SOURCE_TYPES)})"
CK_STAGE = f"stage IN ({quoted(STAGES)})"
CK_CATEGORY = f"category IN ({quoted(CATEGORIES)})"
CK_FLAGS = f"flags <@ ARRAY[{quoted(FLAGS)}]::text[]"
CK_MPP = "NOT (flags @> ARRAY['mpp', 'no_mpp']::text[])"
CK_REJECTED = "stage <> 'rejected' OR reject_reason IS NOT NULL"
CK_EVENT_ACTION = f"action IN ({quoted(EVENT_ACTIONS)})"

IDENTIFIER_WHERE = "id_value IS NOT NULL"
SYMFONIA_WHERE = "symfonia_partner_id IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS finance_counterparties (
    id SERIAL PRIMARY KEY,
    id_type VARCHAR(8) NULL,
    id_value VARCHAR({ID_VALUE_MAX}) NULL,
    name VARCHAR({NAME_MAX}) NOT NULL,
    street VARCHAR(255) NULL,
    postal_code VARCHAR(16) NULL,
    city VARCHAR(120) NULL,
    country VARCHAR(2) NULL,
    email VARCHAR(255) NULL,
    symfonia_partner_id VARCHAR({SYMFONIA_ID_MAX}) NULL,
    cost_account VARCHAR({ACCOUNT_MAX}) NULL,
    revenue_account VARCHAR({ACCOUNT_MAX}) NULL,
    imported_at TIMESTAMPTZ NULL,
    updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_finance_counterparties_id_type CHECK ({CK_ID_TYPE}),
    CONSTRAINT ck_finance_counterparties_id_pair CHECK ({CK_ID_PAIR}),
    CONSTRAINT ck_finance_counterparties_key CHECK ({CK_KEY})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_cost_entries (
    id SERIAL PRIMARY KEY,
    source_type VARCHAR(20) NOT NULL,
    source_id INTEGER NOT NULL,
    from_ksef BOOLEAN NOT NULL,
    stage VARCHAR(10) NOT NULL,
    flags TEXT[] NOT NULL DEFAULT '{{}}'::text[],
    category VARCHAR(12) NOT NULL,
    counterparty_id INTEGER NULL REFERENCES finance_counterparties(id) ON DELETE SET NULL,
    seller_nip VARCHAR(16) NULL,
    received_at TIMESTAMPTZ NOT NULL,
    due_date DATE NULL,
    note TEXT NULL,
    reject_reason VARCHAR({REASON_MAX}) NULL,
    stage_changed_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    stage_changed_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_finance_cost_entries_source UNIQUE (source_type, source_id),
    CONSTRAINT ck_finance_cost_entries_source_type CHECK ({CK_SOURCE_TYPE}),
    CONSTRAINT ck_finance_cost_entries_stage CHECK ({CK_STAGE}),
    CONSTRAINT ck_finance_cost_entries_category CHECK ({CK_CATEGORY}),
    CONSTRAINT ck_finance_cost_entries_flags CHECK ({CK_FLAGS}),
    CONSTRAINT ck_finance_cost_entries_mpp CHECK ({CK_MPP}),
    CONSTRAINT ck_finance_cost_entries_rejected CHECK ({CK_REJECTED})
)""",
    f"""CREATE TABLE IF NOT EXISTS finance_cost_entry_events (
    id SERIAL PRIMARY KEY,
    entry_id INTEGER NOT NULL REFERENCES finance_cost_entries(id) ON DELETE CASCADE,
    action VARCHAR(12) NOT NULL,
    from_stage VARCHAR(10) NULL,
    to_stage VARCHAR(10) NULL,
    detail JSONB NOT NULL DEFAULT '{{}}'::jsonb,
    actor_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_finance_cost_entry_events_action CHECK ({CK_EVENT_ACTION})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_counterparties_identifier "
    f"ON finance_counterparties (id_type, id_value) WHERE {IDENTIFIER_WHERE}",
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_finance_counterparties_symfonia "
    f"ON finance_counterparties (symfonia_partner_id) WHERE {SYMFONIA_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_entries_stage "
    "ON finance_cost_entries (stage, received_at)",
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_entries_seller "
    "ON finance_cost_entries (seller_nip)",
    "CREATE INDEX IF NOT EXISTS ix_finance_cost_entry_events_entry "
    "ON finance_cost_entry_events (entry_id, id)",
)

CONSTRAINT_DDL: tuple[str, ...] = ()

#: Kontrahent z kartoteki po NIP-ie sprzedawcy (tylko polski NIP — tak go
#: trzymają wszystkie trzy źródła).
_COUNTERPARTY_BY_NIP = (
    "(SELECT c.id FROM finance_counterparties c "
    "WHERE c.id_type = 'nip' AND c.id_value = {nip})"
)
_ON_CONFLICT = "ON CONFLICT ON CONSTRAINT uq_finance_cost_entries_source DO NOTHING"


def entry_inserts(*, by_ksef_number: bool = False) -> tuple[str, ...]:
    """``INSERT … SELECT`` wpisów dla faktur źródeł, które ich jeszcze nie mają.

    Faktura z KSeF zaczyna w poczekalni (``received``), PDF wgrany ręcznie od
    razu jako „Do opisu” (``new``) — poczekalnia jest tylko na KSeF, jak w eBI24.
    ``by_ksef_number`` zawęża do jednej faktury (parametr ``:ksef_number``).
    """

    def where(alias: str, source_type: str) -> str:
        # Tylko faktury bez wpisu: sam ``ON CONFLICT`` pobiera wartość sekwencji
        # dla każdego wiersza źródła, więc cogodzinny przebieg zjadałby ``SERIAL``.
        # ``ON CONFLICT`` zostaje jako zabezpieczenie przed wyścigiem.
        missing = (
            "NOT EXISTS (SELECT 1 FROM finance_cost_entries e "
            f"WHERE e.source_type = '{source_type}' AND e.source_id = {alias}.id)"
        )
        if by_ksef_number:
            return f"WHERE {alias}.ksef_number = :ksef_number AND {missing}"
        return f"WHERE {missing}"

    return (
        "INSERT INTO finance_cost_entries "
        "(source_type, source_id, from_ksef, stage, category, seller_nip, "
        "received_at, counterparty_id) "
        "SELECT 'payroll_invoice', p.id, p.source = 'ksef', "
        "CASE WHEN p.source = 'ksef' THEN 'received' ELSE 'new' END, 'team', "
        "p.seller_nip, COALESCE(p.ksef_acquired_at, p.fetched_at, p.created_at), "
        f"{_COUNTERPARTY_BY_NIP.format(nip='p.seller_nip')} "
        f"FROM payroll_invoices p {where('p', 'payroll_invoice')} {_ON_CONFLICT}",
        "INSERT INTO finance_cost_entries "
        "(source_type, source_id, from_ksef, stage, category, seller_nip, "
        "received_at, counterparty_id) "
        "SELECT 'contractor_invoice', x.id, TRUE, 'received', 'contractor', "
        "x.seller_nip, COALESCE(x.acquired_at, x.created_at), "
        f"{_COUNTERPARTY_BY_NIP.format(nip='x.seller_nip')} "
        f"FROM client_contractor_invoices x {where('x', 'contractor_invoice')} "
        f"{_ON_CONFLICT}",
        "INSERT INTO finance_cost_entries "
        "(source_type, source_id, from_ksef, stage, category, seller_nip, "
        "received_at, counterparty_id) "
        "SELECT 'approval_document', a.id, a.source = 'ksef', "
        "CASE WHEN a.source = 'ksef' THEN 'received' ELSE 'new' END, 'office', "
        "a.seller_nip, COALESCE(a.fetched_at, a.created_at), "
        f"{_COUNTERPARTY_BY_NIP.format(nip='a.seller_nip')} "
        f"FROM approval_documents a {where('a', 'approval_document')} "
        f"{_ON_CONFLICT}",
    )


#: Wpisy bez kontrahenta dostają go po NIP-ie (po imporcie kartoteki).
LINK_COUNTERPARTIES = (
    "UPDATE finance_cost_entries e SET counterparty_id = c.id "
    "FROM finance_counterparties c "
    "WHERE e.counterparty_id IS NULL AND e.seller_nip IS NOT NULL "
    "AND c.id_type = 'nip' AND c.id_value = e.seller_nip"
)

ENTRY_INSERTS: tuple[str, ...] = entry_inserts()

DATA_DDL: tuple[str, ...] = (*ENTRY_INSERTS, LINK_COUNTERPARTIES)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS finance_cost_entry_events",
    "DROP TABLE IF EXISTS finance_cost_entries",
    "DROP TABLE IF EXISTS finance_counterparties",
)
