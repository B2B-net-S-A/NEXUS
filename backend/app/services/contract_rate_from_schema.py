"""Stawka z bieżącej umowy w „Stawce od” (15.10.2026) — SQL migracji 0448
i lustra w ``entrypoint.sh``.

JEDNO źródło instrukcji dla ``alembic/versions/0448_rate_from_contracts.py``
i ``entrypoint.sh`` (alembic na prodzie bywa osierocony; ciała wyzwalaczy są
w ``$$``, więc entrypoint importuje ten moduł zamiast przepisywać SQL).

Dopóki osoba ma żywą umowę, „Stawka od” = stawka konsultanta z tej umowy
(``candidate_rate_observations``, klucz ``contract:{id}``). Zmiana umowy albo
harmonogramu jej stawek kolejkuje przeliczenie kandydata:

* ``trg_rate_from_contracts`` — status, osoba, start i pola stawki kosztowej
  (kwota, waluta, jednostka, godziny rozliczeniowe). Warunki w ciele funkcji,
  nie w ``UPDATE OF``: entrypoint poszerza ``contracts.rate_candidate``,
  a Postgres nie zmieni typu kolumny wymienionej w definicji wyzwalacza;
* ``trg_rate_from_contract_rates`` — kroki harmonogramu stawki konsultanta
  (``contract_candidate_rates``).

Kalendarz (start umowy, krok harmonogramu, który właśnie zaczął obowiązywać)
przelicza pętla ``candidate_rate_from`` raz dziennie
(``requeue_live_contracts``). Jednorazowo: osoby z żywymi umowami trafiają do
kolejki (znacznik ``BACKFILL_MARKER``).

Wymaga funkcji ``candidate_rate_from_enqueue`` z ``candidate_rate_from_schema``
(entrypoint wpina ten moduł po niej).
"""

from __future__ import annotations

BACKFILL_MARKER = "0448_rate_from_contracts_queued"

_CONTRACT_FIELDS = (
    "status",
    "candidate_id",
    "start_date",
    "rate_candidate",
    "rate_candidate_currency",
    "currency",
    "rate_unit",
    "billing_hours_per_month",
)


def _changed(fields: tuple[str, ...]) -> str:
    return " OR ".join(f"NEW.{f} IS DISTINCT FROM OLD.{f}" for f in fields)


TRIGGER_DDL = (
    "CREATE OR REPLACE FUNCTION trg_rate_from_contracts() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF TG_OP = 'DELETE' THEN "
    "PERFORM candidate_rate_from_enqueue(OLD.candidate_id); RETURN OLD; END IF; "
    "IF TG_OP = 'INSERT' OR " + _changed(_CONTRACT_FIELDS) + " THEN "
    "PERFORM candidate_rate_from_enqueue(NEW.candidate_id); "
    "IF TG_OP = 'UPDATE' AND NEW.candidate_id IS DISTINCT FROM OLD.candidate_id THEN "
    "PERFORM candidate_rate_from_enqueue(OLD.candidate_id); END IF; "
    "END IF; RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_contracts ON contracts",
    "CREATE TRIGGER trg_rate_from_contracts AFTER INSERT OR UPDATE OR DELETE "
    "ON contracts FOR EACH ROW EXECUTE FUNCTION trg_rate_from_contracts()",
    "CREATE OR REPLACE FUNCTION trg_rate_from_contract_rates() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF TG_OP IN ('UPDATE', 'DELETE') THEN "
    "PERFORM candidate_rate_from_enqueue("
    "(SELECT candidate_id FROM contracts WHERE id = OLD.contract_id)); END IF; "
    "IF TG_OP IN ('INSERT', 'UPDATE') THEN "
    "PERFORM candidate_rate_from_enqueue("
    "(SELECT candidate_id FROM contracts WHERE id = NEW.contract_id)); END IF; "
    "IF TG_OP = 'DELETE' THEN RETURN OLD; END IF; "
    "RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_contract_rates ON contract_candidate_rates",
    "CREATE TRIGGER trg_rate_from_contract_rates AFTER INSERT OR UPDATE OR DELETE "
    "ON contract_candidate_rates FOR EACH ROW "
    "EXECUTE FUNCTION trg_rate_from_contract_rates()",
)

BACKFILL_DDL = (
    "DO $$ BEGIN "
    f"IF NOT EXISTS (SELECT 1 FROM app_settings WHERE key = '{BACKFILL_MARKER}') THEN "
    "INSERT INTO candidate_rate_from_queue (candidate_id) "
    "SELECT DISTINCT ct.candidate_id FROM contracts ct "
    "JOIN candidates c ON c.id = ct.candidate_id "
    "WHERE CAST(ct.status AS text) IN ('active', 'ending') "
    "ON CONFLICT (candidate_id) DO NOTHING; "
    f"INSERT INTO app_settings (key, value) VALUES ('{BACKFILL_MARKER}', "
    "jsonb_build_object('completed_at', clock_timestamp())) "
    "ON CONFLICT (key) DO NOTHING; "
    "END IF; "
    "END $$",
)

ALL_DDL = TRIGGER_DDL + BACKFILL_DDL
