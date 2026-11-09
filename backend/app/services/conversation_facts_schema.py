"""DDL rejestru faktów z rozmów — JEDNO źródło dla migracji 0670 i siatki
w ``entrypoint.sh`` (produkcyjny alembic bywa osierocony).

Jeden wiersz to jeden fakt o osobie z jednego źródła: umiejętność, branża,
certyfikat albo regulacja, potwierdzone albo „nie ma”. Źródło (arkusz, notatka
AI), etap lub notatka, rekrutacja i autor zostają przy wierszu, żeby dało się
cofnąć zapis i pokazać pochodzenie. Cofnięcie stawia ``retired_at``.
"""

from __future__ import annotations

TABLE_DDL: list[str] = [
    """CREATE TABLE IF NOT EXISTS candidate_conversation_facts (
           id BIGSERIAL PRIMARY KEY,
           candidate_id INTEGER NOT NULL REFERENCES candidates (id) ON DELETE CASCADE,
           kind VARCHAR(16) NOT NULL,
           value TEXT NOT NULL,
           value_key TEXT NOT NULL,
           canonical_terms JSONB NOT NULL DEFAULT '[]'::jsonb,
           status VARCHAR(16) NOT NULL,
           source VARCHAR(16) NOT NULL,
           stage_id INTEGER NULL REFERENCES candidate_stages (id) ON DELETE SET NULL,
           note_id INTEGER NULL REFERENCES notes (id) ON DELETE SET NULL,
           job_id INTEGER NULL REFERENCES jobs (id) ON DELETE SET NULL,
           author_id INTEGER NULL REFERENCES users (id) ON DELETE SET NULL,
           evidence TEXT NULL,
           noted_at TIMESTAMPTZ NOT NULL,
           batch VARCHAR(40) NULL,
           retired_at TIMESTAMPTZ NULL,
           created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
           CONSTRAINT ck_candidate_conversation_facts_kind
               CHECK (kind IN ('skill', 'domain', 'certification', 'regulation')),
           CONSTRAINT ck_candidate_conversation_facts_status
               CHECK (status IN ('confirmed', 'absent')),
           CONSTRAINT ck_candidate_conversation_facts_source
               CHECK (source IN ('sheet', 'note_ai')),
           CONSTRAINT ck_candidate_conversation_facts_absent_sheet
               CHECK (status <> 'absent' OR source = 'sheet')
       )""",
    "CREATE INDEX IF NOT EXISTS ix_candidate_conversation_facts_candidate "
    "ON candidate_conversation_facts (candidate_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_conversation_facts_sheet "
    "ON candidate_conversation_facts (candidate_id, job_id, kind, value_key) "
    "WHERE source = 'sheet' AND retired_at IS NULL",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_conversation_facts_note "
    "ON candidate_conversation_facts (candidate_id, kind, value_key) "
    "WHERE source = 'note_ai' AND retired_at IS NULL",
]

DOWNGRADE_DDL: list[str] = ["DROP TABLE IF EXISTS candidate_conversation_facts"]
