"""Publikacja na RocketJobs i JustJoin.IT (Employer Public API 1EP).

Revision ID: 0381_job_boards_jjit_rocketjobs
Revises: 0380_job_client_reference_working_title

* ``portal`` + ``rocketjobs`` — JustJoin.IT i RocketJobs to jedno API
  dostawcy (``jobBoard``), ale dla rekrutera dwa portale.
* ``job_postings``: ``options`` (ustawienia ogłoszenia: kategoria, poziom,
  wymiar, miasto, widełki), ``pending_action`` (``publish|update|close`` —
  worker wie, co zrobić z żywym wierszem), ``remote_state`` (ostatni stan
  z portalu), ``next_attempt_at`` (backoff zamiast ponowienia co tick).
* ``job_board_connections`` — jedno połączone konto firmy na dostawcę
  (tokeny zaszyfrowane ``TokenCipher``). Odświeżenie tokenu idzie pod
  ``FOR UPDATE`` tego wiersza.

Lustro w ``entrypoint.sh`` (alembic na prodzie bywa osierocony) — pilnuje
``test_job_boards_queue.py::test_migration_and_entrypoint_mirror``.
"""

from alembic import op

revision = "0381_job_boards_jjit_rocketjobs"
down_revision = "0380_job_client_reference_working_title"
branch_labels = None
depends_on = None

ENUM_STATEMENTS = ("ALTER TYPE portal ADD VALUE IF NOT EXISTS 'rocketjobs'",)

COLUMN_STATEMENTS = (
    "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS options JSONB",
    "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS pending_action VARCHAR(10)",
    "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS remote_state VARCHAR(20)",
    "ALTER TABLE job_postings ADD COLUMN IF NOT EXISTS next_attempt_at TIMESTAMPTZ",
)

CONSTRAINT_STATEMENTS = (
    """DO $$ BEGIN
        ALTER TABLE job_postings ADD CONSTRAINT ck_job_postings_pending_action
            CHECK (pending_action IS NULL
                   OR pending_action IN ('publish', 'update', 'close'));
    EXCEPTION WHEN duplicate_object THEN NULL; END $$""",
)

TABLE_STATEMENTS = (
    """CREATE TABLE IF NOT EXISTS job_board_connections (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(20) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    access_token_ct TEXT NULL,
    refresh_token_ct TEXT NOT NULL,
    expires_at TIMESTAMPTZ NULL,
    organization_units JSONB NOT NULL DEFAULT '{}',
    account_label VARCHAR(255) NULL,
    connected_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    connected_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_refresh_at TIMESTAMPTZ NULL,
    last_error VARCHAR(300) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_job_board_connections_status
        CHECK (status IN ('active', 'reconnect_required'))
)""",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for statement in ENUM_STATEMENTS:
            op.execute(statement)
    for statement in COLUMN_STATEMENTS + CONSTRAINT_STATEMENTS + TABLE_STATEMENTS:
        op.execute(statement)


# Runda 8 (R8-N15-2): wartość enuma `rocketjobs` zostaje po downgrade (Postgres
# nie ma DROP VALUE), a kod sprzed tej rewizji jej nie zna — `select(JobPosting)`
# na takim wierszu rzuca `LookupError` (500). Downgrade odmawia, zamiast kasować
# publikacje (ogłoszenie mogło zostać na portalu bez możliwości zamknięcia).
#
# Runda 9 (R9-V3-5): to samo dotyczy JustJoin.IT. Downgrade kasuje
# `pending_action`/`remote_state` i `job_board_connections`, więc publikacja
# w toku (zaległe zamknięcie, żywe ogłoszenie) traciłaby jedyną drogę do
# zamknięcia na portalu, a połączone konto — tokeny. Wiersze zakończone
# (`removed`/`expired` bez zaległej akcji) niczego nie tracą i nie blokują.
# Kolumny i tabela sprawdzane przed zapytaniem — plan zapytania o brakującą
# kolumnę padłby błędem zamiast odmowy (lustro strażnika 0388).
REFUSE_WITH_ROCKETJOBS_POSTINGS = """DO $$
DECLARE
    live_jjit boolean := false;
BEGIN
    IF EXISTS (SELECT 1 FROM job_postings WHERE portal::text = 'rocketjobs') THEN
        RAISE EXCEPTION 'Downgrade 0381 odmawia: job_postings ma publikacje na RocketJobs, których kod sprzed tej rewizji nie odczyta. Zamknij je i usuń wiersze ręcznie albo zostaw tę rewizję.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = 'job_postings'
          AND column_name IN ('pending_action', 'remote_state')
        HAVING count(*) = 2
    ) THEN
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM job_postings'
            || ' WHERE pending_action IS NOT NULL'
            || ' OR (remote_state IS NOT NULL'
            || ' AND remote_state NOT IN (''removed'', ''expired'')))'
            INTO live_jjit;
        IF live_jjit THEN
            RAISE EXCEPTION 'Downgrade 0381 odmawia: job_postings ma publikacje w toku (zaległa akcja albo żywe ogłoszenie na portalu), a downgrade usuwa stan potrzebny do ich zamknięcia. Zamknij ogłoszenia na portalu albo zostaw tę rewizję.';
        END IF;
    END IF;
    IF to_regclass('job_board_connections') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM job_board_connections) THEN
            RAISE EXCEPTION 'Downgrade 0381 odmawia: job_board_connections ma połączone konto portalu (tokeny zginęłyby razem z tabelą). Odłącz konto albo zostaw tę rewizję.';
        END IF;
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_ROCKETJOBS_POSTINGS)
    op.execute("DROP TABLE IF EXISTS job_board_connections")
    op.execute(
        "ALTER TABLE job_postings DROP CONSTRAINT IF EXISTS ck_job_postings_pending_action"
    )
    for column in ("next_attempt_at", "remote_state", "pending_action", "options"):
        op.execute(f"ALTER TABLE job_postings DROP COLUMN IF EXISTS {column}")
    # Wartość enuma zostaje — Postgres nie ma `ALTER TYPE … DROP VALUE`.
