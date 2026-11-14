"""Środki trwałe i WNiP (K6): SQL migracji ``0703_ledger_assets`` i lustra entrypointu.

Jedno źródło DDL dla ``alembic/versions/0703_ledger_assets.py`` i lustra
``entrypoint.sh`` (``app/services/hr_schema_bundle.py``); każda instrukcja
idempotentna. Plan: https://claude.ai/artifact/U9Z3unvSK62Ff5U36hkaar
(NEXUS zastępuje Symfonię Środki Trwałe).

* ``ledger_assets`` — ewidencja: numer inwentarzowy, nazwa, rodzaj (środek
  trwały albo WNiP), symbol KŚT (klasyfikacja 2016), data przyjęcia, wartość
  początkowa z przyjęcia (grosze, bez ulepszeń), konto środka (010/020) i konto
  umorzenia (070/071), MPK (zmienia go tylko dokument MT), metoda i stawka
  amortyzacji osobno dla planu bilansowego i podatkowego, współczynnik metody
  degresywnej, stan (``in_use`` / ``liquidated`` / ``sold`` z datą zbycia),
  powiązanie z pozycją „Sprzętu” (jedna pozycja — jeden środek). Środek
  przeniesiony z Symfonii (import albo ręcznie ze stanem) ma
  ``opening_month`` — umorzenie bilansowe i podatkowe na koniec tego miesiąca
  (dla degresywnej także na początek jego roku); takiego środka nie przyjmuje
  się OT w księdze, bo jego wartość i umorzenie przychodzą bilansem otwarcia.
* ``ledger_asset_operations`` — dokumenty środka: ``OT`` (przyjęcie, także
  z faktury kosztowej z kolejki kosztów), ``UL`` (ulepszenie — zwiększenie
  wartości), ``MT`` (zmiana MPK), ``LT`` (likwidacja), ``SP`` (sprzedaż).
  Numer ``OT 1/2026`` (typ, kolejny w roku). OT, UL, LT i SP mają dokument
  w księdze (źródło ``asset_operation`` / id operacji); OT bez konta
  przeciwstawnego to przyjęcie bez zapisu w księdze. ``title`` to opis środka
  zamrożony przy dokumencie (numer inwentarzowy i nazwa) — późniejsza zmiana
  nazwy nie zmienia opisu dokumentu w księdze, więc zatwierdzony zapis nie
  wraca jako „zmieniony po zatwierdzeniu”.
"""

from __future__ import annotations

from app.services.consultant_portal_schema import quoted
from app.services.ledger_schema import ACCOUNT_MAX, MPK_MAX

ASSET_KINDS: tuple[str, ...] = ("fixed", "intangible")
METHODS: tuple[str, ...] = ("linear", "degressive", "one_off", "none")
STATUSES: tuple[str, ...] = ("in_use", "liquidated", "sold")
#: OT przyjęcie, UL ulepszenie, MT zmiana MPK, LT likwidacja, SP sprzedaż.
OPERATION_TYPES: tuple[str, ...] = ("OT", "UL", "MT", "LT", "SP")

INVENTORY_MAX = 40
NAME_MAX = 200
KST_MAX = 16
NOTE_MAX = 500
OPERATION_NUMBER_MAX = 40
OPERATION_NOTE_MAX = 300
OPERATION_TITLE_MAX = 250

CK_ASSET_KIND = f"kind IN ({quoted(ASSET_KINDS)})"
CK_ASSET_STATUS = f"status IN ({quoted(STATUSES)})"
CK_ASSET_DISPOSED = "(status = 'in_use') = (disposed_on IS NULL)"
CK_ASSET_VALUE = "initial_value > 0"
CK_ASSET_METHODS = (
    f"balance_method IN ({quoted(METHODS)}) AND tax_method IN ({quoted(METHODS)})"
)
CK_ASSET_RATES = "balance_rate BETWEEN 0 AND 100 AND tax_rate BETWEEN 0 AND 100"
CK_ASSET_COEFFICIENT = "coefficient BETWEEN 1 AND 2"
CK_ASSET_OPENING = (
    "(opening_month IS NULL AND opening_balance = 0 AND opening_tax = 0 "
    "AND opening_balance_year IS NULL AND opening_tax_year IS NULL) "
    "OR (opening_month IS NOT NULL AND EXTRACT(DAY FROM opening_month) = 1 "
    "AND opening_balance BETWEEN 0 AND initial_value "
    "AND opening_tax BETWEEN 0 AND initial_value)"
)
CK_OPERATION_TYPE = f"op_type IN ({quoted(OPERATION_TYPES)})"
CK_OPERATION_AMOUNT = "amount IS NULL OR amount > 0"
CK_OPERATION_MPK = "(op_type = 'MT') = (mpk_to IS NOT NULL)"

ASSET_EQUIPMENT_WHERE = "equipment_item_id IS NOT NULL"
OPERATION_COST_WHERE = "cost_entry_id IS NOT NULL"

TABLE_DDL: tuple[str, ...] = (
    f"""CREATE TABLE IF NOT EXISTS ledger_assets (
    id SERIAL PRIMARY KEY,
    inventory_number VARCHAR({INVENTORY_MAX}) NOT NULL,
    name VARCHAR({NAME_MAX}) NOT NULL,
    kind VARCHAR(10) NOT NULL DEFAULT 'fixed',
    kst VARCHAR({KST_MAX}) NULL,
    accepted_on DATE NOT NULL,
    initial_value BIGINT NOT NULL,
    asset_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    depreciation_account VARCHAR({ACCOUNT_MAX}) NOT NULL,
    mpk VARCHAR({MPK_MAX}) NOT NULL,
    balance_method VARCHAR(10) NOT NULL,
    balance_rate NUMERIC(5, 2) NOT NULL,
    tax_method VARCHAR(10) NOT NULL,
    tax_rate NUMERIC(5, 2) NOT NULL,
    coefficient NUMERIC(3, 2) NOT NULL DEFAULT 2.0,
    status VARCHAR(10) NOT NULL DEFAULT 'in_use',
    disposed_on DATE NULL,
    equipment_item_id INTEGER NULL REFERENCES equipment_items(id) ON DELETE SET NULL,
    opening_month DATE NULL,
    opening_balance BIGINT NOT NULL DEFAULT 0,
    opening_tax BIGINT NOT NULL DEFAULT 0,
    opening_balance_year BIGINT NULL,
    opening_tax_year BIGINT NULL,
    note VARCHAR({NOTE_MAX}) NOT NULL DEFAULT '',
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_assets_inventory UNIQUE (inventory_number),
    CONSTRAINT ck_ledger_assets_kind CHECK ({CK_ASSET_KIND}),
    CONSTRAINT ck_ledger_assets_status CHECK ({CK_ASSET_STATUS}),
    CONSTRAINT ck_ledger_assets_disposed CHECK ({CK_ASSET_DISPOSED}),
    CONSTRAINT ck_ledger_assets_value CHECK ({CK_ASSET_VALUE}),
    CONSTRAINT ck_ledger_assets_methods CHECK ({CK_ASSET_METHODS}),
    CONSTRAINT ck_ledger_assets_rates CHECK ({CK_ASSET_RATES}),
    CONSTRAINT ck_ledger_assets_coefficient CHECK ({CK_ASSET_COEFFICIENT}),
    CONSTRAINT ck_ledger_assets_opening CHECK ({CK_ASSET_OPENING})
)""",
    f"""CREATE TABLE IF NOT EXISTS ledger_asset_operations (
    id SERIAL PRIMARY KEY,
    asset_id INTEGER NOT NULL REFERENCES ledger_assets(id) ON DELETE CASCADE,
    op_type VARCHAR(2) NOT NULL,
    number VARCHAR({OPERATION_NUMBER_MAX}) NOT NULL,
    op_date DATE NOT NULL,
    amount BIGINT NULL,
    mpk_from VARCHAR({MPK_MAX}) NULL,
    mpk_to VARCHAR({MPK_MAX}) NULL,
    counter_account VARCHAR({ACCOUNT_MAX}) NULL,
    cost_entry_id INTEGER NULL REFERENCES finance_cost_entries(id) ON DELETE SET NULL,
    title VARCHAR({OPERATION_TITLE_MAX}) NOT NULL DEFAULT '',
    note VARCHAR({OPERATION_NOTE_MAX}) NOT NULL DEFAULT '',
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_ledger_asset_operations_number UNIQUE (number),
    CONSTRAINT ck_ledger_asset_operations_type CHECK ({CK_OPERATION_TYPE}),
    CONSTRAINT ck_ledger_asset_operations_amount CHECK ({CK_OPERATION_AMOUNT}),
    CONSTRAINT ck_ledger_asset_operations_mpk CHECK ({CK_OPERATION_MPK})
)""",
)

COLUMN_DDL: tuple[str, ...] = ()

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_ledger_assets_equipment "
    f"ON ledger_assets (equipment_item_id) WHERE {ASSET_EQUIPMENT_WHERE}",
    "CREATE INDEX IF NOT EXISTS ix_ledger_assets_status "
    "ON ledger_assets (status, accepted_on)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_asset_operations_asset "
    "ON ledger_asset_operations (asset_id, op_date)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_asset_operations_month "
    "ON ledger_asset_operations (op_date)",
    "CREATE INDEX IF NOT EXISTS ix_ledger_asset_operations_cost "
    f"ON ledger_asset_operations (cost_entry_id) WHERE {OPERATION_COST_WHERE}",
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

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP TABLE IF EXISTS ledger_asset_operations",
    "DROP TABLE IF EXISTS ledger_assets",
)
