"""DDL profilu „Kogo szukamy” rekrutacji — JEDNO źródło dla migracji 0728
i siatki w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``job_role_profiles``: jeden wiersz na rekrutację, zapisany dopiero przy
„Popraw” w porcji (bez wiersza profil liczy się z tytułu i profilu Championa).
``excluded`` = etykiety „Nie proponujemy” wpisane ręcznie, ``dismissed`` =
etykiety nauczone z odrzuceń, które ktoś zdjął z listy (klucze casefold).
Reguła: ``docs/claude/rekrutacja-tablica/porcja-kogo-szukamy.md``.
"""

from __future__ import annotations

LEVELS: tuple[str, ...] = ("wykonawca", "lider", "dowolny")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS job_role_profiles (
           job_id INTEGER PRIMARY KEY REFERENCES jobs (id) ON DELETE CASCADE,
           role VARCHAR(120) NULL,
           specialty VARCHAR(120) NULL,
           technology VARCHAR(120) NULL,
           level VARCHAR(16) NOT NULL DEFAULT 'dowolny'
               CONSTRAINT ck_job_role_profiles_level CHECK (level IN ({_in(LEVELS)})),
           excluded JSONB NOT NULL DEFAULT '[]'::jsonb,
           dismissed JSONB NOT NULL DEFAULT '[]'::jsonb,
           updated_by INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
       )""",
]

DOWNGRADE_DDL: list[str] = ["DROP TABLE IF EXISTS job_role_profiles"]
