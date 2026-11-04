"""Zmiany stawki kandydata w trakcie procesu — SQL migracji 0418 i lustra
w ``entrypoint.sh`` (alembic na prodzie bywa osierocony, a ciało wyzwalacza
jest w ``$$``, więc entrypoint importuje ten moduł).

Jeden wiersz ``candidate_rate_changes`` = jedna zgłoszona zmiana stawki pary
(kandydat, rekrutacja) z całym cyklem życia: zgłoszona → w negocjacji →
ustalona → zamknięta (decyzje Artura 04.10.2026, makiety
https://claude.ai/artifact/2bJy59VoHb67EcX5wj1tz9). Do tej migracji korekta
stawki nadpisywała wiersz etapu bez śladu i bez powiadomienia DL.

Wyzwalacz dopisuje kandydata do ``candidate_rate_from_queue`` (0414), bo
zgłoszona i ustalona stawka to obserwacje „Stawki od”.
"""

from __future__ import annotations

STATUSES = ("noted", "requested", "negotiating", "agreed", "closed", "superseded")
OPEN_STATUSES = ("requested", "negotiating", "agreed")
# 0424: `screening` — stawka z jednego formularza screeningu. Istniejący CHECK
# poszerza `source_constraint_ddl` (``CREATE TABLE IF NOT EXISTS`` go nie zmieni).
SOURCES = (
    "debrief",
    "manual",
    "recruitments_tab",
    "profile",
    "card",
    "move",
    "screening",
)
REASONS = ("conversation", "email", "typo", "other")
NEGOTIABLE = ("no", "maybe", "unknown")
OUTCOMES = ("lower", "kept", "withdrew")
DECISIONS = ("raise_client", "keep_client", "withdraw", "auto")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{v}'" for v in values)


TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS candidate_rate_changes ("
    "id SERIAL PRIMARY KEY, "
    "candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE, "
    "job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE, "
    "stage_id INTEGER NULL REFERENCES candidate_stages(id) ON DELETE SET NULL, "
    "previous_amount NUMERIC(12,2) NULL, "
    "previous_unit VARCHAR(20) NULL, "
    "previous_currency VARCHAR(3) NULL, "
    "previous_hourly NUMERIC(10,2) NULL, "
    "requested_amount NUMERIC(12,2) NOT NULL, "
    "requested_unit VARCHAR(20) NOT NULL, "
    "requested_currency VARCHAR(3) NOT NULL DEFAULT 'PLN', "
    "requested_hourly NUMERIC(10,2) NULL, "
    "agreed_amount NUMERIC(12,2) NULL, "
    "agreed_unit VARCHAR(20) NULL, "
    "agreed_currency VARCHAR(3) NULL, "
    "agreed_hourly NUMERIC(10,2) NULL, "
    "source VARCHAR(20) NOT NULL, "
    "reason VARCHAR(20) NOT NULL DEFAULT 'other', "
    "note TEXT NULL, "
    "negotiable VARCHAR(10) NULL, "
    "feedback_id INTEGER NULL REFERENCES interview_feedback(id) ON DELETE SET NULL, "
    "status VARCHAR(20) NOT NULL, "
    "requires_decision BOOLEAN NOT NULL DEFAULT false, "
    "board_column VARCHAR(30) NULL, "
    "negotiator_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "negotiation_target_hourly NUMERIC(10,2) NULL, "
    "negotiation_due DATE NULL, "
    "outcome VARCHAR(10) NULL, "
    "outcome_note TEXT NULL, "
    "outcome_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "outcome_at TIMESTAMPTZ NULL, "
    "decision VARCHAR(20) NULL, "
    "decided_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "decided_at TIMESTAMPTZ NULL, "
    "created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL, "
    "created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    "updated_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
    f"CONSTRAINT ck_candidate_rate_changes_status CHECK (status IN ({_in(STATUSES)})), "
    f"CONSTRAINT ck_candidate_rate_changes_source CHECK (source IN ({_in(SOURCES)})), "
    f"CONSTRAINT ck_candidate_rate_changes_reason CHECK (reason IN ({_in(REASONS)})), "
    "CONSTRAINT ck_candidate_rate_changes_negotiable CHECK "
    f"(negotiable IS NULL OR negotiable IN ({_in(NEGOTIABLE)})), "
    "CONSTRAINT ck_candidate_rate_changes_outcome CHECK "
    f"(outcome IS NULL OR outcome IN ({_in(OUTCOMES)})), "
    "CONSTRAINT ck_candidate_rate_changes_decision CHECK "
    f"(decision IS NULL OR decision IN ({_in(DECISIONS)})), "
    "CONSTRAINT ck_candidate_rate_changes_note CHECK "
    "(note IS NULL OR char_length(note) <= 1000))",
    "CREATE INDEX IF NOT EXISTS ix_candidate_rate_changes_pair "
    "ON candidate_rate_changes (candidate_id, job_id, created_at DESC)",
    "CREATE INDEX IF NOT EXISTS ix_candidate_rate_changes_job "
    "ON candidate_rate_changes (job_id)",
    # Jedna otwarta sprawa na parę — druga zmiana zastępuje pierwszą
    # (``superseded``) w tej samej transakcji.
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_candidate_rate_changes_open "
    "ON candidate_rate_changes (candidate_id, job_id) "
    f"WHERE status IN ({_in(OPEN_STATUSES)})",
    "CREATE INDEX IF NOT EXISTS ix_candidate_rate_changes_open_status "
    f"ON candidate_rate_changes (status) WHERE status IN ({_in(OPEN_STATUSES)})",
)

TRIGGER_DDL = (
    "CREATE OR REPLACE FUNCTION trg_rate_from_rate_changes() RETURNS trigger "
    "LANGUAGE plpgsql AS $$ BEGIN "
    "IF TG_OP = 'DELETE' THEN PERFORM candidate_rate_from_enqueue(OLD.candidate_id); RETURN OLD; END IF; "
    "IF TG_OP = 'INSERT' OR NEW.requested_amount IS DISTINCT FROM OLD.requested_amount "
    "OR NEW.agreed_amount IS DISTINCT FROM OLD.agreed_amount "
    "OR NEW.status IS DISTINCT FROM OLD.status THEN "
    "PERFORM candidate_rate_from_enqueue(NEW.candidate_id); END IF; "
    "RETURN NEW; END $$",
    "DROP TRIGGER IF EXISTS trg_rate_from_rate_changes ON candidate_rate_changes",
    "CREATE TRIGGER trg_rate_from_rate_changes AFTER INSERT OR UPDATE OR DELETE "
    "ON candidate_rate_changes FOR EACH ROW EXECUTE FUNCTION trg_rate_from_rate_changes()",
)

NOTIFICATION_ENUM_DDL = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_rate_change'",
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_rate_change_task'",
)

ALL_DDL = TABLE_DDL + TRIGGER_DDL


def source_constraint_ddl(sources: tuple[str, ...] = SOURCES) -> str:
    """CHECK źródła zmiany stawki: DROP + ADD w jednym bloku (0424).

    Timeout zamka wycofuje obie instrukcje naraz, a następny start ponawia.
    Downgrade 0424 woła to samo z listą sprzed ``screening``.
    """

    return (
        "DO $$ BEGIN "
        "ALTER TABLE candidate_rate_changes "
        "DROP CONSTRAINT IF EXISTS ck_candidate_rate_changes_source; "
        "ALTER TABLE candidate_rate_changes ADD CONSTRAINT "
        f"ck_candidate_rate_changes_source CHECK (source IN ({_in(sources)})); "
        "END $$"
    )
