"""DDL wersji Profilu Championa — JEDNO źródło dla migracji 0730 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

``champion_profile_revisions``: jeden wiersz na zapis zmieniający treść profilu
rekrutacji w pracy (``published``). ``changes`` to lista pozycji z
``champion_profile_changes.describe_changes``, ``before``/``after`` to
znormalizowane profile (do ponownego policzenia różnicy, gdy zmieni się jej
opis), ``note`` to zdanie Delivery Leada „na co klient kładzie nacisk”.

``champion_profile_change_reads``: do której wersji dana osoba kliknęła
„Przeczytane” w danej rekrutacji.
Reguła: ``docs/claude/rekrutacja-tworzenie/profil-championa-co-sie-zmienilo.md``.
"""

from __future__ import annotations

NOTE_MAX_CHARS = 600

TABLE_DDL: list[str] = [
    f"""CREATE TABLE IF NOT EXISTS champion_profile_revisions (
           id SERIAL PRIMARY KEY,
           job_id INTEGER NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
           author_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           author_name VARCHAR(200) NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           changes JSONB NOT NULL DEFAULT '[]'::jsonb,
           before JSONB NULL,
           after JSONB NULL,
           note TEXT NULL
               CONSTRAINT ck_champion_profile_revisions_note CHECK (note IS NULL OR char_length(note) <= {NOTE_MAX_CHARS}),
           note_updated_at TIMESTAMPTZ NULL
       )""",
    """CREATE INDEX IF NOT EXISTS ix_champion_profile_revisions_job
           ON champion_profile_revisions (job_id, id DESC)""",
    """CREATE TABLE IF NOT EXISTS champion_profile_change_reads (
           job_id INTEGER NOT NULL REFERENCES jobs (id) ON DELETE CASCADE,
           user_id INTEGER NOT NULL REFERENCES users (id) ON DELETE CASCADE,
           last_seen_revision_id INTEGER NOT NULL,
           seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           PRIMARY KEY (job_id, user_id)
       )""",
]

DOWNGRADE_DDL: list[str] = [
    "DROP TABLE IF EXISTS champion_profile_change_reads",
    "DROP TABLE IF EXISTS champion_profile_revisions",
]
