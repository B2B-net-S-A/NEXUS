"""Karta rekomendacji — SQL migracji 0413 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0413_recommendation_cards.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony); test
``test_recommendation_cards.py`` sprawdza, że każda stoi w entrypoincie
dosłownie.

* ``recommendation_cards`` — jedna karta na parę (kandydat, rekrutacja).
  ``fields_notes`` to pola odczytane z notatek rekrutera (przeliczane od zera
  przy każdej zmianie notatek pary), ``fields_manual`` to pola wpisane
  w NEXUSIE — zawsze wygrywają. ``note_answers`` to pytania i odpowiedzi
  z notatki, tylko do odczytu.
* ``notes.card_parsed_hash`` — odcisk (treść + rekrutacja + nagrobek + wersja
  parsera), z którym notatka została ostatnio przeliczona. Pętla importu
  wybiera wiersze z innym odciskiem, więc ``job_id`` dopisany surowym SQL-em
  po imporcie z Traffita łapie się sam.
"""

from __future__ import annotations

TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS recommendation_cards ("
    "id SERIAL PRIMARY KEY, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "fields_notes JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "fields_manual JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "note_answers JSONB NOT NULL DEFAULT '{}'::jsonb, "
    "updated_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "CONSTRAINT uq_recommendation_cards_pair UNIQUE (candidate_id, job_id))"
)

COLUMN_DDL = (
    "CREATE INDEX IF NOT EXISTS ix_recommendation_cards_job ON recommendation_cards (job_id)",
    "ALTER TABLE notes ADD COLUMN IF NOT EXISTS card_parsed_hash VARCHAR(32) NULL",
    "CREATE INDEX IF NOT EXISTS ix_notes_card_kinds ON notes (id) "
    "WHERE kind IN ('card', 'screening_facts')",
)
