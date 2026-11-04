"""Przypięte notatki, odpowiedzi i notatki systemowe (migracja 0399, 29.09.2026).

JEDNO źródło SQL dla migracji ``0399_notes_pin_replies`` i lustra
w ``entrypoint.sh`` (alembic na prodzie bywa osierocony). Test
``test_notes_pin_replies.py`` sprawdza, że każda instrukcja stoi w entrypoincie
dosłownie.

* ``notes.pinned_at`` / ``pinned_by`` — przypięcie wspólne dla zespołu.
* ``notes.parent_note_id`` — odpowiedź na notatkę (jeden poziom), kaskadą
  z notatką główną.
* ``recruitment_processes.entry_meta`` — wynik auto-matcha przy procesie
  zamiast notatki.
* ``note_reply`` — powiadomienie autora notatki o odpowiedzi.
* Stare notatki automatów („Auto-match score: …”, „Auto-match NN/100 —
  kandydat dodany automatycznie…”) dostają ``external_source = 'system'`` —
  NIE są kasowane, lista chowa je domyślnie. Jednorazowo (znacznik
  w ``app_settings``), bo to skan całej tabeli notatek.
"""

from __future__ import annotations

SYSTEM_NOTES_MARKER = "0399_auto_match_notes_system"

ENUM_DDL = ("ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'note_reply'",)

COLUMN_DDL = (
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS pinned_at TIMESTAMPTZ NULL",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS pinned_by INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS parent_note_id INTEGER NULL "
    "REFERENCES notes(id) ON DELETE CASCADE",
    "CREATE INDEX IF NOT EXISTS ix_notes_parent_note_id ON notes (parent_note_id)",
    "CREATE INDEX IF NOT EXISTS ix_notes_candidate_pinned "
    "ON notes (candidate_id, pinned_at) WHERE pinned_at IS NOT NULL",
    "ALTER TABLE recruitment_processes ADD COLUMN IF NOT EXISTS entry_meta JSONB NULL",
)

# Wzorce treści dwóch automatów sprzed 29.09.2026:
# * scraper JJIT/RocketJobs: „Źródło: … \nAuto-match score: NN/100 …”,
# * auto-match z CV: „Auto-match NN/100 — kandydat dodany automatycznie po …”.
SYSTEM_NOTES_BACKFILL = (
    "DO $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = '0399_auto_match_notes_system') THEN "
    "UPDATE notes SET external_source = 'system' "
    "WHERE external_source IS NULL AND ("
    "content LIKE '%Auto-match score:%' "
    "OR (content LIKE 'Auto-match %' AND content LIKE '%kandydat dodany automatycznie%')); "
    "INSERT INTO app_settings (key, value) VALUES ("
    "'0399_auto_match_notes_system', "
    "jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; "
    "END IF; "
    "END $$"
)
