"""Serie faktur jak w eBI24 (16.11.2026): SQL migracji ``0716_invoice_series_ebi24`` i lustra entrypointu.

Do serii E4 (``PL``, ``UE``, ``ZAL``, ``KOR``) dochodzą ``BEN`` — refaktury
benefitów rozliczane kompensatą, bez rachunku na fakturze (eBI24:
``303/9/2026/Benefit``) — i ``KORUE`` — korekty faktur UE (eBI24:
``1/10/2026/KORUE``). Decyzja Artura z 16.11.2026: osobna seria Benefit jak
w eBI24. Lista serii jest w ``client_invoice_issue_schema.SERIES``; tutaj tylko
przebudowa CHECK-ów w bazach, które powstały przed zmianą (blok ``DO``
sprawdza, czy CHECK zna już ``KORUE``, więc przy kolejnych startach nic nie robi).
"""

from __future__ import annotations

from app.services.client_invoice_issue_schema import CK_ISSUED_SERIES, CK_SERIES_CODE

_REBUILDS = (
    ("client_invoice_series", "ck_client_invoice_series_code", CK_SERIES_CODE),
    ("client_issued_invoices", "ck_client_issued_invoices_series", CK_ISSUED_SERIES),
)

TABLE_DDL: tuple[str, ...] = ()
COLUMN_DDL: tuple[str, ...] = ()
INDEX_DDL: tuple[str, ...] = ()

CONSTRAINT_DDL: tuple[str, ...] = tuple(
    f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = '{name}'
          AND pg_get_constraintdef(oid) NOT LIKE '%KORUE%'
    ) THEN
        ALTER TABLE {table} DROP CONSTRAINT {name};
        ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({check});
    END IF;
END $$"""
    for table, name, check in _REBUILDS
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

#: Powrót: faktury w seriach BEN/KORUE nie zmieszczą się w starym CHECK-u —
#: downgrade ich nie kasuje, tylko odpada na ADD CONSTRAINT.
_OLD = "'PL', 'UE', 'ZAL', 'KOR'"
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE client_invoice_series DROP CONSTRAINT IF EXISTS ck_client_invoice_series_code",
    f"ALTER TABLE client_invoice_series ADD CONSTRAINT ck_client_invoice_series_code "
    f"CHECK (series_code IN ({_OLD}))",
    "ALTER TABLE client_issued_invoices DROP CONSTRAINT IF EXISTS ck_client_issued_invoices_series",
    f"ALTER TABLE client_issued_invoices ADD CONSTRAINT ck_client_issued_invoices_series "
    f"CHECK (series_code IN ({_OLD}))",
)
