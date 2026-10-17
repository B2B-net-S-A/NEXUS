"""„Ludzie w NEXUSIE” — umowy z ludźmi (etap 5, E5): SQL migracji ``0469_hr_agreements`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0469_hr_agreements.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w pozostałych
``*_schema.py``; każda instrukcja idempotentna.

Umowy z osobami zespołu wszystkich form (B2B biura, zlecenie, aneksy) z wgrywanych wzorów,
podpis przez Autenti i przepisanie danych do kartoteki po podpisie. Tabele dopisuje agent E5.
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
