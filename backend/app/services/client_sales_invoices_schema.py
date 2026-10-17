"""Faktury sprzedażowe do klientów z KSeF (etap 5, E8 cz. 1): SQL migracji ``0470_client_sales_invoices`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0470_client_sales_invoices.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w pozostałych
``*_schema.py``; każda instrukcja idempotentna.

Faktury, w których spółka jest sprzedawcą (KSeF, Subject1), dopasowane do zamówień klientów,
zapłata z wyciągu i zaległości u Delivery Leada. Tabele dopisuje agent E8.
"""

from __future__ import annotations

TABLE_DDL: tuple[str, ...] = ()
COLUMN_DDL: tuple[str, ...] = ()
INDEX_DDL: tuple[str, ...] = ()
CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ()
DOWNGRADE_DDL: tuple[str, ...] = ()

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
