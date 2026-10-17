"""„Ludzie w NEXUSIE” — dokumenty osoby (e-teczka, etap 5, E4): SQL migracji ``0468_hr_documents`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0468_hr_documents.py`` i ``entrypoint.sh``
(przez ``app/services/hr_schema_bundle.py``). Kontrakt modułu jak w pozostałych
``*_schema.py``; każda instrukcja idempotentna.

Dokumenty osoby przy kartotece: rodzaj, plik, „ważny do”, krąg widzących, retencja po odejściu.
Tabele i ich opis dopisuje agent E4 (koordynator założył pusty kontrakt modułu).
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
