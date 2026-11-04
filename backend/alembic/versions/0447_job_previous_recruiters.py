"""„Poprzedni rekruter” — uśpieni rekruterzy rekrutacji i dwa typy dzwonków.

Revision ID: 0447_job_previous_recruiters
Revises: 0446_automation_role

Prośba Head of Recruitment (14.10.2026), decyzje Artura tego samego dnia:
zamknięcie rekrutacji albo zejście z P1 przenosi zespół do „Poprzedni
rekruter”; powrót na P1 albo ponowne otwarcie przy P1 przywraca go samo.
``jobs.recruiter_id`` i ręcznie dopisani zostają — reguła zespołu pomija
osoby z otwartym wierszem tej tabeli (``cleared_at IS NULL``).

* ``via``: skąd osoba była w zespole (prowadzący, przypisanie, współpracownik);
  ``assignment_source`` — źródło przypisania (``auto`` wraca jako przypisanie
  automatu, nie trwały wpis).
* ``reason``: ``closed`` (zamknięcie) albo ``priority`` (zejście z P1).
* ``cleared_reason``: ``restored`` | ``dismissed`` („Usuń z poprzednich”) |
  ``readded`` (człowiek dodał osobę) | ``removed`` | ``skipped`` (konto
  nieaktywne albo bez roli rekrutera przy powrocie).

Bez danych wstecz: reguła działa od pierwszego zdarzenia po wdrożeniu.

Typy dzwonków ``recruiter_parked`` / ``recruiter_restored`` — osobne, bo
dedup dobowy (osoba, typ, rekrutacja) połknąłby dzwonek tego samego typu co
``request_assignment_changed`` przy ponownym otwarciu.

Lustro w ``entrypoint.sh`` — pilnuje ``test_previous_recruiters_migration.py``.
"""

from alembic import op

revision = "0447_job_previous_recruiters"
down_revision = "0446_automation_role"
branch_labels = None
depends_on = None

CREATE_TABLE = """CREATE TABLE IF NOT EXISTS job_previous_recruiters (
    id SERIAL PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    via VARCHAR(20) NOT NULL,
    assignment_source VARCHAR(20) NULL,
    reason VARCHAR(20) NOT NULL,
    parked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    parked_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    cleared_at TIMESTAMPTZ NULL,
    cleared_reason VARCHAR(20) NULL,
    cleared_by_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    CONSTRAINT ck_job_previous_recruiters_via
        CHECK (via IN ('owner', 'assignment', 'collaborator')),
    CONSTRAINT ck_job_previous_recruiters_assignment_source
        CHECK (assignment_source IS NULL OR assignment_source IN ('auto', 'manual')),
    CONSTRAINT ck_job_previous_recruiters_reason
        CHECK (reason IN ('closed', 'priority')),
    CONSTRAINT ck_job_previous_recruiters_cleared_reason
        CHECK (cleared_reason IS NULL OR cleared_reason IN
            ('restored', 'dismissed', 'readded', 'removed', 'skipped'))
)"""
CREATE_JOB_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_job_previous_recruiters_job_id "
    "ON job_previous_recruiters (job_id)"
)
CREATE_OPEN_INDEX = (
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_job_previous_recruiters_open "
    "ON job_previous_recruiters (job_id, user_id) WHERE cleared_at IS NULL"
)
CREATE_USER_OPEN_INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_job_previous_recruiters_user_open "
    "ON job_previous_recruiters (user_id) WHERE cleared_at IS NULL"
)

ADD_PARKED_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'recruiter_parked'"
)
ADD_RESTORED_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'recruiter_restored'"
)

# Wartości enuma zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — dzwonek tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ('recruiter_parked', 'recruiter_restored')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0447 odmawia: notifications ma wpisy recruiter_parked/recruiter_restored, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)
    op.execute(CREATE_JOB_INDEX)
    op.execute(CREATE_OPEN_INDEX)
    op.execute(CREATE_USER_OPEN_INDEX)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_PARKED_TYPE)
        op.execute(ADD_RESTORED_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DROP TABLE IF EXISTS job_previous_recruiters")
