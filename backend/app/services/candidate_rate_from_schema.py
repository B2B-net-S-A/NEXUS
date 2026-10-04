"""„Stawka od” kandydata — SQL migracji 0414 i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0414_candidate_rate_from.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony — entrypoint importuje
ten moduł, bo ciała wyzwalaczy są w ``$$``).

* ``candidates.rate_from_*`` — najniższa stawka PLN/h z ostatnich 18 miesięcy,
  liczona przez ``services/candidate_rate_from.py``. Zapisywana surowym SQL-em,
  więc nie rusza ``updated_at`` (alerty zapisanych wyszukiwań czytają tę datę).
* ``candidate_rate_decisions`` — „Nie licz jako minimum” rekrutera.
* ``candidate_rate_from_queue`` — kandydaci do przeliczenia. Wyzwalacze na
  kartach, etapach, stawce profilu i zgłoszeniach dopisują do niej kandydata,
  także przy surowym SQL-u importu Traffita i pętli kart.
"""

from __future__ import annotations

BACKFILL_MARKER = "0414_candidate_rate_from_queued"

TABLE_DDL = (
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_from_hourly NUMERIC(10,2) NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_from_at TIMESTAMPTZ NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_from_source VARCHAR(30) NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_from_job_id INTEGER NULL "
    "REFERENCES jobs(id) ON DELETE SET NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_from_stale BOOLEAN NOT NULL DEFAULT false",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_from_computed_at TIMESTAMPTZ NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_latest_hourly NUMERIC(10,2) NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_latest_at TIMESTAMPTZ NULL",
    "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS rate_observation_count INTEGER NOT NULL DEFAULT 0",
    "CREATE TABLE IF NOT EXISTS candidate_rate_decisions ("
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "observation_key VARCHAR(80) NOT NULL, "
    "decision VARCHAR(10) NOT NULL CONSTRAINT ck_candidate_rate_decisions_decision "
    "CHECK (decision = 'exclude'), "
    "decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "decided_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "PRIMARY KEY (candidate_id, observation_key))",
    "CREATE TABLE IF NOT EXISTS candidate_rate_from_queue ("
    "candidate_id INTEGER PRIMARY KEY REFERENCES candidates(id) ON DELETE CASCADE, "
    "queued_at TIMESTAMPTZ NOT NULL DEFAULT now())",
    "CREATE INDEX IF NOT EXISTS ix_candidates_rate_from_hourly "
    "ON candidates (rate_from_hourly) WHERE rate_from_computed_at IS NOT NULL",
)

TRIGGER_DDL = (
    "CREATE OR REPLACE FUNCTION candidate_rate_from_enqueue(cid integer) RETURNS void "
    "LANGUAGE sql AS $$ "
    "INSERT INTO candidate_rate_from_queue (candidate_id) "
    "SELECT cid WHERE cid IS NOT NULL AND EXISTS (SELECT 1 FROM candidates WHERE id = cid) "
    "ON CONFLICT (candidate_id) DO NOTHING $$",
    # Karty rekomendacji: każda zmiana pól z notatek albo wpisanych ręcznie.
    "CREATE OR REPLACE FUNCTION trg_rate_from_cards() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF TG_OP = 'DELETE' THEN PERFORM candidate_rate_from_enqueue(OLD.candidate_id); RETURN OLD; END IF; "
    "IF TG_OP = 'INSERT' OR NEW.fields_notes IS DISTINCT FROM OLD.fields_notes "
    "OR NEW.fields_manual IS DISTINCT FROM OLD.fields_manual "
    "OR NEW.candidate_id IS DISTINCT FROM OLD.candidate_id THEN "
    "PERFORM candidate_rate_from_enqueue(NEW.candidate_id); "
    "IF TG_OP = 'UPDATE' AND NEW.candidate_id IS DISTINCT FROM OLD.candidate_id THEN "
    "PERFORM candidate_rate_from_enqueue(OLD.candidate_id); END IF; "
    "END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_cards ON recommendation_cards",
    "CREATE TRIGGER trg_rate_from_cards AFTER INSERT OR UPDATE OR DELETE "
    "ON recommendation_cards FOR EACH ROW EXECUTE FUNCTION trg_rate_from_cards()",
    # Etapy: tylko gdy stawka jest albo była niepusta.
    "CREATE OR REPLACE FUNCTION trg_rate_from_stages() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF TG_OP = 'DELETE' THEN "
    "IF OLD.expected_rate_value IS NOT NULL THEN PERFORM candidate_rate_from_enqueue(OLD.candidate_id); END IF; "
    "RETURN OLD; END IF; "
    "IF TG_OP = 'INSERT' THEN "
    "IF NEW.expected_rate_value IS NOT NULL THEN PERFORM candidate_rate_from_enqueue(NEW.candidate_id); END IF; "
    "RETURN NEW; END IF; "
    "IF (NEW.expected_rate_value IS NOT NULL OR OLD.expected_rate_value IS NOT NULL) AND ("
    "NEW.expected_rate_value IS DISTINCT FROM OLD.expected_rate_value "
    "OR NEW.expected_rate_unit IS DISTINCT FROM OLD.expected_rate_unit "
    "OR NEW.expected_rate_currency IS DISTINCT FROM OLD.expected_rate_currency "
    "OR NEW.candidate_id IS DISTINCT FROM OLD.candidate_id) THEN "
    "PERFORM candidate_rate_from_enqueue(NEW.candidate_id); "
    "IF NEW.candidate_id IS DISTINCT FROM OLD.candidate_id THEN "
    "PERFORM candidate_rate_from_enqueue(OLD.candidate_id); END IF; "
    "END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_stages ON candidate_stages",
    "CREATE TRIGGER trg_rate_from_stages AFTER INSERT OR UPDATE OR DELETE "
    "ON candidate_stages FOR EACH ROW EXECUTE FUNCTION trg_rate_from_stages()",
    # Stawka profilu (wszystkie ścieżki zapisu, także formularz kariery).
    "CREATE OR REPLACE FUNCTION trg_rate_from_profile() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF NEW.expected_rate_hourly IS DISTINCT FROM OLD.expected_rate_hourly "
    "OR NEW.expected_rate_currency IS DISTINCT FROM OLD.expected_rate_currency THEN "
    "PERFORM candidate_rate_from_enqueue(NEW.id); END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_profile ON candidates",
    "CREATE TRIGGER trg_rate_from_profile AFTER UPDATE OF expected_rate_hourly, "
    "expected_rate_currency ON candidates FOR EACH ROW EXECUTE FUNCTION trg_rate_from_profile()",
    "CREATE OR REPLACE FUNCTION trg_rate_from_profile_insert() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF NEW.expected_rate_hourly IS NOT NULL THEN "
    "INSERT INTO candidate_rate_from_queue (candidate_id) VALUES (NEW.id) "
    "ON CONFLICT (candidate_id) DO NOTHING; END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_profile_insert ON candidates",
    "CREATE TRIGGER trg_rate_from_profile_insert AFTER INSERT ON candidates "
    "FOR EACH ROW EXECUTE FUNCTION trg_rate_from_profile_insert()",
    # Zgłoszenie osoby już w bazie: stawka z formularza żyje tylko w zgłoszeniu.
    "CREATE OR REPLACE FUNCTION trg_rate_from_submissions() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF NEW.matched_candidate_id IS NOT NULL AND NEW.raw_payload ? 'expected_rate_hourly' THEN "
    "PERFORM candidate_rate_from_enqueue(NEW.matched_candidate_id); END IF; "
    "RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_submissions ON application_submissions",
    "CREATE TRIGGER trg_rate_from_submissions AFTER INSERT OR UPDATE OF matched_candidate_id "
    "ON application_submissions FOR EACH ROW EXECUTE FUNCTION trg_rate_from_submissions()",
)

# Jednorazowo: każdy kandydat z jakimkolwiek źródłem stawki trafia do kolejki.
# Liczy pętla ``candidate_rate_from`` po starcie, paczkami.
BACKFILL_DDL = (
    "DO $$ BEGIN "
    "IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = '0414_candidate_rate_from_queued') THEN "
    "INSERT INTO candidate_rate_from_queue (candidate_id) "
    "SELECT id FROM candidates WHERE expected_rate_hourly IS NOT NULL "
    "UNION SELECT candidate_id FROM recommendation_cards "
    "WHERE fields_notes ? 'rate' OR fields_manual ? 'rate' "
    "UNION SELECT candidate_id FROM candidate_stages WHERE expected_rate_value IS NOT NULL "
    "UNION SELECT matched_candidate_id FROM application_submissions "
    "WHERE matched_candidate_id IS NOT NULL AND raw_payload ? 'expected_rate_hourly' "
    "ON CONFLICT (candidate_id) DO NOTHING; "
    "INSERT INTO app_settings (key, value) VALUES ("
    "'0414_candidate_rate_from_queued', "
    "jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; "
    "END IF; "
    "END $$",
)

ALL_DDL = TABLE_DDL + TRIGGER_DDL + BACKFILL_DDL
