"""„Ludzie w NEXUSIE” — kartoteka idzie za kontem: SQL migracji ``0476_hr_profile_follows_account`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0476_hr_profile_follows_account.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Decyzja Artura 19.10.2026 („Konto decyduje + lista rozjazdów”): każde aktywne
konto pracownicze ma kartotekę. Brakującą zakłada automat
(``services/hr/account_profiles.py``) jako „aktywny” z formą i przełożonym
„do uzupełnienia”:

* ``employee_profiles.employment_type_pending`` — forma do uzupełnienia
  (``employment_type`` ma wtedy tylko wartość domyślną, ekrany pokazują
  „do uzupełnienia”; znacznik gaśnie przy pierwszym zapisie formy),
* ``employee_profiles.created_from_account`` — kartotekę założył automat
  z konta; bez przełożonego = przełożony „do uzupełnienia”.
"""

from __future__ import annotations

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE employee_profiles ADD COLUMN IF NOT EXISTS "
    "employment_type_pending BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE employee_profiles ADD COLUMN IF NOT EXISTS "
    "created_from_account BOOLEAN NOT NULL DEFAULT false",
)

INDEX_DDL: tuple[str, ...] = ()
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
    "ALTER TABLE employee_profiles DROP COLUMN IF EXISTS created_from_account",
    "ALTER TABLE employee_profiles DROP COLUMN IF EXISTS employment_type_pending",
)
