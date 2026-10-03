"""Rodzaj notatki — SQL migracji 0412 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0412_note_kind.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_note_kinds.py`` sprawdza, że każda stoi w entrypoincie dosłownie.

* ``notes.kind`` — rodzaj nadawany regułą ``services/note_kinds.py``.
  Istniejące wiersze uzupełnia pętla ``note_kind_backfill`` po starcie
  (reguły są w Pythonie, więc nie da się ich policzyć samym SQL-em).
* „Reply” z Traffita to odpowiedź na notatkę (rozmowa Delivery Lead ↔
  rekruter), a import oznaczał ją jako mail: 3 955 wierszy liczyło się
  w follow-upie jako kontakt z kandydatem. Jednorazowa zmiana typu na
  ``general`` — bez ruszania ``updated_at`` (odcisk nocnego odczytu faktów).
"""

from __future__ import annotations

REPLY_RETYPE_MARKER = "0412_traffit_reply_notes_retyped"

COLUMN_DDL = (
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS kind VARCHAR(24) NULL",
    "CREATE INDEX IF NOT EXISTS ix_notes_kind_pending ON notes (id) WHERE kind IS NULL",
)

REPLY_RETYPE = (
    "DO $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = '0412_traffit_reply_notes_retyped') THEN "
    "UPDATE notes n SET note_type = 'general' FROM activities a "
    "WHERE a.external_source = 'traffit' AND a.action = 'traffit:Reply' "
    "AND n.source_ref = 'traffit:activity:' || a.external_id "
    "AND n.note_type = 'email'; "
    "INSERT INTO app_settings (key, value) VALUES ("
    "'0412_traffit_reply_notes_retyped', "
    "jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; "
    "END IF; "
    "END $$"
)
