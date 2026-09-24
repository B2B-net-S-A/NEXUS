"""Follow-up z kandydatem, gdy klient milczy — wyniki telefonów.

Revision ID: 0371_candidate_followups
Revises: 0370_teams_prep_transcripts

Decyzje Artura 24.09.2026: gdy klient nie odpowiada 14 dni po wysłaniu CV,
jeden rekruter dzwoni do kandydata („nadal jesteś w procesie”) i powtarza to
co 14 dni. Zadanie należy do OSOBY, nie procesu — kandydat w pięciu procesach
dostaje jeden telefon. Kto dzwoni i kiedy, liczy się przy odczycie
(``services/candidate_followups.py``); ta tabela trzyma wyłącznie to, czego
nie da się wyliczyć: wynik telefonu, „nie odebrał”, „oddzwoń” i przejęcie
rundy („Zrobię to ja”).

Kandydat CASCADE — twarde usunięcie osoby (art. 17 RODO) zabiera też ślad
telefonów. Lustro w ``entrypoint.sh`` (prod alembic bywa osierocony) —
pilnuje ``tests/test_candidate_followups_migration_mirror.py``.
"""

from alembic import op

revision = "0371_candidate_followups"
down_revision = "0370_teams_prep_transcripts"
branch_labels = None
depends_on = None

OUTCOMES = ("connected", "changed", "no_answer", "callback", "claim")

CREATE_CANDIDATE_FOLLOWUPS = """CREATE TABLE IF NOT EXISTS candidate_followups (
    id BIGSERIAL PRIMARY KEY,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    outcome VARCHAR(16) NOT NULL,
    callback_on DATE NULL,
    note_id INTEGER NULL REFERENCES notes(id) ON DELETE SET NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_candidate_followups_outcome
        CHECK (outcome IN ('connected','changed','no_answer','callback','claim')),
    CONSTRAINT ck_candidate_followups_callback
        CHECK ((outcome = 'callback') = (callback_on IS NOT NULL))
)"""

CREATE_CANDIDATE_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_candidate_followups_candidate_created "
    "ON candidate_followups (candidate_id, created_at DESC)"
)

ENUM_NOTIFICATION = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'candidate_followup_signal'"
)

DDL_STATEMENTS = [CREATE_CANDIDATE_FOLLOWUPS, CREATE_CANDIDATE_INDEX]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(ENUM_NOTIFICATION)
    for statement in DDL_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS candidate_followups")
    # Wartość enumu zostaje — Postgres nie ma `ALTER TYPE … DROP VALUE`.
