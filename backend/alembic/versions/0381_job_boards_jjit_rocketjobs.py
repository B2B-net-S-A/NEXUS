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


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS job_board_connections")
    op.execute(
        "ALTER TABLE job_postings DROP CONSTRAINT IF EXISTS ck_job_postings_pending_action"
    )
    for column in ("next_attempt_at", "remote_state", "pending_action", "options"):
        op.execute(f"ALTER TABLE job_postings DROP COLUMN IF EXISTS {column}")
    # Wartość enuma zostaje — Postgres nie ma `ALTER TYPE … DROP VALUE`.
