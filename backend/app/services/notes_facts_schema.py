"""Dane z notatek do pól profilu (07.10.2026) — SQL migracji 0422 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0422_notes_facts_to_fields.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony; ciało wyzwalacza jest
w ``$$``, więc entrypoint importuje ten moduł zamiast przepisywać SQL).

* ``trg_rate_from_notes`` — notatka DL-a z wpisem „X/Y” (stawka do klienta /
  oczekiwanie kandydata) jest obserwacją „Stawki od” (``note:{id}``), więc jej
  zapis, edycja i usunięcie dopisują kandydata do kolejki przeliczeń — także
  przy surowym SQL-u importu Traffita. Wyzwalacz sprawdza tylko kształt
  („liczba/liczba”); ostateczną regułę stosuje
  ``client_rate_notes.parse_dl_pair`` przy przeliczeniu.
* ``ck_candidate_languages_provenance`` przyjmuje źródło ``notes`` (języki
  zaobserwowane w notatkach, ``candidate_language_writer``).
* Jednorazowo: kandydaci z istniejącymi wpisami „X/Y” trafiają do kolejki
  „Stawki od” (znacznik ``BACKFILL_MARKER``).
"""

from __future__ import annotations

BACKFILL_MARKER = "0422_notes_dl_pair_rate_from_queued"

# Lustro ``client_rate_notes.DL_PAIR_SQL_PATTERN`` i ``DL_PAIR_KINDS``
# (pilnuje test) — tu literalnie, bo instrukcje idą do bazy wprost.
_PAIR_PATTERN = r"[0-9]{2,3}\s*/\s*[0-9]{2,3}"
_KINDS = "('dl_rate', 'human')"


def _matches(row: str) -> str:
    return (
        f"{row}.candidate_id IS NOT NULL AND {row}.kind IN {_KINDS} "
        f"AND {row}.content ~ '{_PAIR_PATTERN}'"
    )


TRIGGER_DDL = (
    "CREATE OR REPLACE FUNCTION trg_rate_from_notes() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF TG_OP IN ('UPDATE', 'DELETE') AND "
    + _matches("OLD")
    + " THEN PERFORM candidate_rate_from_enqueue(OLD.candidate_id); END IF; "
    "IF TG_OP IN ('INSERT', 'UPDATE') AND "
    + _matches("NEW")
    + " THEN PERFORM candidate_rate_from_enqueue(NEW.candidate_id); END IF; "
    "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; "
    "RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_notes ON notes",
    # Bez `card_parsed_hash`, `pinned_*` itd. — te zapisy nie zmieniają wpisu.
    "CREATE TRIGGER trg_rate_from_notes AFTER INSERT OR DELETE OR UPDATE OF "
    "content, kind, candidate_id, job_id, parent_note_id, source_deleted_at, "
    "source_created_at, created_at ON notes "
    "FOR EACH ROW EXECUTE FUNCTION trg_rate_from_notes()",
)

LANGUAGE_PROVENANCE_DDL = (
    "ALTER TABLE candidate_languages DROP CONSTRAINT IF EXISTS "
    "ck_candidate_languages_provenance",
    "DO $$ BEGIN "
    "ALTER TABLE candidate_languages ADD CONSTRAINT ck_candidate_languages_provenance "
    "CHECK (provenance IN ('manual', 'cv', 'traffit', 'talent_radar', 'tr_legacy', "
    "'csv', 'legacy', 'unknown', 'notes')); "
    "EXCEPTION WHEN duplicate_object THEN NULL; END $$",
)

BACKFILL_DDL = (
    "DO $$ BEGIN "
    f"IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = '{BACKFILL_MARKER}') THEN "
    "INSERT INTO candidate_rate_from_queue (candidate_id) "
    "SELECT DISTINCT n.candidate_id FROM notes n "
    "JOIN candidates c ON c.id = n.candidate_id "
    "WHERE " + _matches("n") + " AND n.parent_note_id IS NULL "
    "ON CONFLICT (candidate_id) DO NOTHING; "
    f"INSERT INTO app_settings (key, value) VALUES ('{BACKFILL_MARKER}', "
    "jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; "
    "END IF; "
    "END $$",
)

ALL_DDL = TRIGGER_DDL + LANGUAGE_PROVENANCE_DDL + BACKFILL_DDL
