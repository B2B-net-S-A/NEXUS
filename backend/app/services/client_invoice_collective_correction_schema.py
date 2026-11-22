"""Korekta zbiorcza rabatu od obrotu (22.11.2026): SQL migracji ``0750_rebate_collective_correction`` i lustra entrypointu.

Decyzja Artura z 16.11.2026 (Nordea): za miesiąc, w którym obrót roku przekroczył
próg, wystawiamy jedną korektę zbiorczą (art. 106j ust. 3) na różnicę stawek od
części obrotu ponad próg. Korekta wskazuje wszystkie faktury miesiąca z KSeF, a nie
jedną fakturę NEXUSA, więc ``corrects_id`` jest pusty, a dane korekty leżą w
``client_issued_invoices.collective_correction`` (JSONB)::

    {"kind": "rebate", "year": 2026, "month": 10,
     "period": "01.10.2026-31.10.2026", "correction_type": "2",
     "invoices": [{"number": "…", "issue_date": "2026-10-31", "ksef_number": "…"}],
     "rate_diff": "0.5", "excess": "…", "threshold_currency": "EUR"}

Przebudowa CHECK-u ``ck_client_issued_invoices_correction``: ``KOR`` ma albo
``corrects_id``, albo ``collective_correction`` (nigdy obu). Unikalny indeks
pilnuje jednej korekty na klienta, miesiąc i walutę (wycofana się nie liczy).
Blok ``DO`` sprawdza, czy CHECK zna już nową kolumnę, więc przy kolejnych
startach nic nie robi. Zmiana jest dodaniem: stary kod takich wierszy nie pisze,
a jego zapisy (``KOR`` z ``corrects_id``) nowy CHECK przyjmuje.
"""

from __future__ import annotations

from app.services.client_invoice_issue_schema import (
    CK_ISSUED_CORRECTION,
    COLLECTIVE_WHERE,
)

_NAME = "ck_client_issued_invoices_correction"

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE client_issued_invoices "
    "ADD COLUMN IF NOT EXISTS collective_correction JSONB NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE UNIQUE INDEX IF NOT EXISTS uq_client_issued_invoices_collective_month "
    "ON client_issued_invoices (client_id, period_year, period_month, currency) "
    f"WHERE {COLLECTIVE_WHERE}",
)

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{_NAME}'
          AND pg_get_constraintdef(oid) NOT LIKE '%collective_correction%'
    ) THEN
        ALTER TABLE client_issued_invoices DROP CONSTRAINT {_NAME};
        ALTER TABLE client_issued_invoices ADD CONSTRAINT {_NAME} CHECK ({CK_ISSUED_CORRECTION});
    END IF;
END $$""",
)

DATA_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)

TABLES: tuple[str, ...] = ()

#: Powrót: korekty zbiorcze nie zmieszczą się w starym CHECK-u — downgrade ich
#: nie kasuje, tylko odpada na ADD CONSTRAINT.
DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS uq_client_issued_invoices_collective_month",
    f"ALTER TABLE client_issued_invoices DROP CONSTRAINT IF EXISTS {_NAME}",
    f"ALTER TABLE client_issued_invoices ADD CONSTRAINT {_NAME} "
    "CHECK ((invoice_type = 'KOR') = (corrects_id IS NOT NULL))",
    "ALTER TABLE client_issued_invoices DROP COLUMN IF EXISTS collective_correction",
)
