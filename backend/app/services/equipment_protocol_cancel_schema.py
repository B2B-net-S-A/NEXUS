"""Sprzęt — anulowanie protokołu: SQL migracji ``0611_equipment_protocol_cancel`` i lustra entrypointu.

JEDNO źródło instrukcji dla ``alembic/versions/0611_equipment_protocol_cancel.py``
i ``entrypoint.sh`` (przez ``app/services/hr_schema_bundle.py``). Kontrakt
modułu jak w pozostałych ``*_schema.py``; każda instrukcja idempotentna.

Decyzja Artura z 28.10.2026: protokół przed podpisem da się poprawić,
a protokół niepotwierdzony — anulować z powodem. Stan ``anulowany`` był
w CHECK od 0464; tu dochodzi kto, kiedy i dlaczego.
"""

from __future__ import annotations

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE equipment_protocols ADD COLUMN IF NOT EXISTS "
    "cancelled_at TIMESTAMPTZ NULL",
    "ALTER TABLE equipment_protocols ADD COLUMN IF NOT EXISTS "
    "cancelled_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE equipment_protocols ADD COLUMN IF NOT EXISTS cancel_reason TEXT NULL",
)

INDEX_DDL: tuple[str, ...] = ()
CONSTRAINT_DDL: tuple[str, ...] = ()
DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ()

DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE equipment_protocols DROP COLUMN IF EXISTS cancel_reason",
    "ALTER TABLE equipment_protocols DROP COLUMN IF EXISTS cancelled_by",
    "ALTER TABLE equipment_protocols DROP COLUMN IF EXISTS cancelled_at",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
