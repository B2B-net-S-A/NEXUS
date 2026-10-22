"""DDL źródła wejścia ``system`` (osoba dodana przez silnik dopełniania
„Nowych”) — JEDNO źródło dla migracji 0514. ``entrypoint.sh`` trzyma tę samą
listę literalnie (blok 0352), bo co start zdejmuje i zakłada CHECK od nowa.
"""

from __future__ import annotations

ENTRY_SOURCES: tuple[str, ...] = (
    "added_manual",
    "application",
    "proposal",
    "reassign",
    "auto_match",
    "import",
    # 0514 (23.10.2026): silnik dopełniania „Nowych”.
    "system",
)


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


def entry_source_ddl(values: tuple[str, ...]) -> list[str]:
    return [
        "ALTER TABLE recruitment_processes "
        "DROP CONSTRAINT IF EXISTS ck_recruitment_processes_entry_source",
        "ALTER TABLE recruitment_processes ADD CONSTRAINT "
        "ck_recruitment_processes_entry_source CHECK "
        f"(entry_source IS NULL OR entry_source IN ({_in(values)}))",
    ]


CONSTRAINT_DDL: list[str] = entry_source_ddl(ENTRY_SOURCES)
DOWNGRADE_DDL: list[str] = entry_source_ddl(ENTRY_SOURCES[:-1])
