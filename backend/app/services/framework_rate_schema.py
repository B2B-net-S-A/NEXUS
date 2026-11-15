"""Limit z umowy ramowej (F1, 15.11.2026) — SQL migracji ``0708_framework_rate_categories``.

Jedno źródło DDL dla migracji i lustra ``entrypoint.sh``; każda instrukcja
idempotentna i dodaje (nowa tabela, kolumny NULL), więc stary kod działa na
nowym schemacie (``podstawy/migracje-zgodne-wstecz.md``).

* ``rate_card_adders`` — dopłata za technologię premium z umowy ramowej
  klienta (np. Kafka +20%) i lista par kategoria/poziom, dla których umowa ją
  dopuszcza. Dane klienta, wpisywane w aplikacji (repo jest publiczne).
* ``contracts.client_rate_card_id`` — kategoria i poziom z umowy ramowej
  (pozycja ``rate_cards``), ``rate_card_source`` (``coa`` = z zamówienia
  klienta, ``dl`` = wybrał Delivery Lead), ``rate_card_coa_label`` — surowa
  etykieta z ostatniego COA (różnica z cennikiem jest widoczna, nie zgadywana).
* ``contracts.framework_addon_*`` — przyznana dopłata. Nie zmienia zamówienia
  ani stawki przychodowej; podnosi tylko limit (krok ``contract_framework_rates``).
  Potwierdzenie po stronie klienta (kto, kiedy, dowód) jest obowiązkowe.
"""

from __future__ import annotations

TABLE_DDL: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS rate_card_adders (
        id SERIAL PRIMARY KEY,
        client_id INTEGER NOT NULL REFERENCES clients (id) ON DELETE CASCADE,
        technology VARCHAR(100) NOT NULL,
        percent NUMERIC(5, 2) NOT NULL,
        eligible JSONB NOT NULL DEFAULT '[]'::jsonb,
        valid_from DATE NULL,
        valid_to DATE NULL,
        notes TEXT NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        CONSTRAINT ck_rate_card_adders_percent CHECK (percent > 0 AND percent <= 100),
        CONSTRAINT ck_rate_card_adders_validity CHECK (
            valid_from IS NULL OR valid_to IS NULL OR valid_from <= valid_to
        )
    )
    """,
    "CREATE INDEX IF NOT EXISTS ix_rate_card_adders_client_id ON rate_card_adders (client_id)",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS client_rate_card_id INTEGER NULL "
    "REFERENCES rate_cards (id) ON DELETE SET NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS rate_card_source VARCHAR(8) NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS rate_card_coa_label VARCHAR(255) NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_technology VARCHAR(100) NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_percent NUMERIC(5, 2) NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_confirmed_by VARCHAR(255) NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_confirmed_on DATE NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_evidence TEXT NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_set_by_id INTEGER NULL "
    "REFERENCES users (id) ON DELETE SET NULL",
    "ALTER TABLE contracts ADD COLUMN IF NOT EXISTS framework_addon_set_at TIMESTAMPTZ NULL",
    "CREATE INDEX IF NOT EXISTS ix_contracts_client_rate_card_id ON contracts (client_rate_card_id)",
)

ALL_DDL = TABLE_DDL

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_contracts_client_rate_card_id",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_set_at",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_set_by_id",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_evidence",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_confirmed_on",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_confirmed_by",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_percent",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS framework_addon_technology",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS rate_card_coa_label",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS rate_card_source",
    "ALTER TABLE contracts DROP COLUMN IF EXISTS client_rate_card_id",
    "DROP TABLE IF EXISTS rate_card_adders",
)
