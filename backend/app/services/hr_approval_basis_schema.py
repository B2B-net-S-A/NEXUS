"""„Ludzie w NEXUSIE” — podstawa w umowie przy premii poza umową: SQL migracji ``0491_approval_contract_basis`` i lustra entrypointu.

Decyzja Artura 21.10.2026: uznaniowa nagroda od koordynatora to dla PIP cecha
wynagrodzenia ze stosunku pracy (od 08.07.2026 PIP może sam stwierdzić
stosunek pracy). Wniosek o premię dla osoby na B2B (także z formą „do
uzupełnienia”) wymaga więc podstawy: punktu umowy albo numeru aneksu, który
to wynagrodzenie przewiduje. Wymóg pilnuje serwis (forma żyje w kartotece,
nie w wierszu zgody), baza pilnuje tylko kształtu: podstawa jest wyłącznie
przy premii.
"""

from __future__ import annotations

CONTRACT_BASIS_MAX_LENGTH = 200

CK_CONTRACT_BASIS = "contract_basis IS NULL OR kind = 'bonus'"

TABLE_DDL: tuple[str, ...] = ()

COLUMN_DDL: tuple[str, ...] = (
    "ALTER TABLE approval_requests ADD COLUMN IF NOT EXISTS "
    f"contract_basis VARCHAR({CONTRACT_BASIS_MAX_LENGTH}) NULL",
)

INDEX_DDL: tuple[str, ...] = ()

CONSTRAINT_DDL: tuple[str, ...] = (
    f"""DO $$ BEGIN
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint WHERE conname = 'ck_approval_requests_contract_basis'
        ) THEN
            ALTER TABLE approval_requests ADD CONSTRAINT ck_approval_requests_contract_basis
                CHECK ({CK_CONTRACT_BASIS});
        END IF;
    END $$""",
)

DATA_DDL: tuple[str, ...] = ()
TABLES: tuple[str, ...] = ()
DOWNGRADE_DDL: tuple[str, ...] = (
    "ALTER TABLE approval_requests DROP CONSTRAINT IF EXISTS "
    "ck_approval_requests_contract_basis",
    "ALTER TABLE approval_requests DROP COLUMN IF EXISTS contract_basis",
)

ALL_DDL: tuple[str, ...] = (
    *TABLE_DDL,
    *COLUMN_DDL,
    *INDEX_DDL,
    *CONSTRAINT_DDL,
    *DATA_DDL,
)
