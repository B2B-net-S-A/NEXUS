"""Rekrutacja „Wstrzymana” (``work_state = on_hold``) i dwa dzwonki.

Revision ID: 0793_job_hold
Revises: 0792_cv_page1_highlight_ai

Zgłoszenie rekruterki z 26.11.2026: zaproponowała kandydatowi projekt i zrobiła
weryfikację, a dopiero potem Delivery Lead powiedział, że klient wstrzymał
rekrutację. Decyzja Artura z 26.11.2026: osobny stan pracy ``on_hold`` obok
„Klient milczy” (``services/job_hold.py``).

* CHECK ``ck_jobs_work_state`` zna ``on_hold``,
* ``jobs.hold_reason`` / ``hold_review_on`` / ``hold_ended_at``,
* ``notificationtype`` + ``job_hold_changed`` (mail obowiązkowy) i
  ``job_hold_check``.

Same dodania — stary kod działa na nowym schemacie. Jedno źródło DDL:
``app/services/job_hold_schema.py``; lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.job_hold_schema import COLUMN_STATEMENTS, ENUM_STATEMENTS

revision = "0793_job_hold"
down_revision = "0792_cv_page1_highlight_ai"
branch_labels = None
depends_on = None

# Etykiet enuma Postgres nie usuwa, a kod sprzed tej rewizji nie zna ani stanu
# ``on_hold``, ani tych typów dzwonka — wiersz z nimi dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM jobs WHERE work_state = 'on_hold')
       OR EXISTS (
           SELECT 1 FROM notifications
           WHERE notification_type::text IN ('job_hold_changed', 'job_hold_check')
       ) THEN
        RAISE EXCEPTION 'Downgrade 0793 odmawia: są rekrutacje wstrzymane albo wpisy job_hold_*, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""

RESTORE_0371_CHECK = (
    "ALTER TABLE jobs DROP CONSTRAINT IF EXISTS ck_jobs_work_state",
    "ALTER TABLE jobs ADD CONSTRAINT ck_jobs_work_state "
    "CHECK (work_state IN ('to_review', 'searching', 'client_silent', 'finished'))",
)


def upgrade() -> None:
    # ADD VALUE poza transakcją migracji.
    with op.get_context().autocommit_block():
        for statement in ENUM_STATEMENTS:
            op.execute(statement)
    for statement in COLUMN_STATEMENTS:
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for statement in RESTORE_0371_CHECK:
        op.execute(statement)
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS hold_ended_at")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS hold_review_on")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS hold_reason")
