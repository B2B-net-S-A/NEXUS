"""Zastępca do Cpro we wniosku urlopowym: SQL migracji ``0618_leave_cpro_substitute`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0618_leave_cpro_substitute.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Decyzja Artura z 29.10.2026: osoba od Cpro wskazuje we własnym wniosku, kto
w tym czasie wrzuca kandydatów Nordei do Cpro. Zwykły zastępca wniosku
(``substitute_user_id``) to akceptacje i poczta — osoba od Cpro bywa
w Finansach, a Cpro przejmuje ktoś z rekrutacji, więc to osobne pole.
``ON DELETE SET NULL``: zastępca do Cpro nie jest częścią wniosku, którą
trzeba zachować, gdy konto zniknie (przy odczycie i tak liczą się aktywne).
"""

from __future__ import annotations

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE leave_requests ADD COLUMN IF NOT EXISTS "
    "cpro_substitute_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
)

INDEX_DDL: tuple[str, ...] = (
    "CREATE INDEX IF NOT EXISTS ix_leave_requests_cpro_substitute "
    "ON leave_requests (user_id, start_date) WHERE cpro_substitute_user_id IS NOT NULL",
)

CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ()

DOWNGRADE_DDL: tuple[str, ...] = (
    "DROP INDEX IF EXISTS ix_leave_requests_cpro_substitute",
    "ALTER TABLE leave_requests DROP COLUMN IF EXISTS cpro_substitute_user_id",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
