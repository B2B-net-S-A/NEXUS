"""Rekrutacje bez ruchu: powód ``no_activity``, „Jeszcze trwa”, dzwonek.

Revision ID: 0616_job_idle_close
Revises: 0615_job_twins

Decyzja Artura 28.10.2026: 14 dni bez CV do klienta i bez odpowiedzi klienta
= przypomnienie do Delivery Leada, 21 dni = także Head of Recruitment, 28 dni
= NEXUS zamyka rekrutację jako przegraną (``services/job_idle.py``).

* ``jobclosereason`` + ``no_activity`` (nadaje tylko NEXUS),
* ``notificationtype`` + ``job_idle_reminder``,
* ``jobs.idle_snoozed_at`` / ``idle_snoozed_by`` — „Jeszcze trwa” liczy od nowa.

Lustro w safety-net ``entrypoint.sh`` — prod alembic bywa osierocony.
"""

from alembic import op

revision = "0616_job_idle_close"
down_revision = "0615_job_twins"
branch_labels = None
depends_on = None

# Etykiet enuma Postgres nie usuwa, a kod sprzed tej rewizji ich nie zna —
# wiersz z taką wartością dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM jobs WHERE close_reason::text = 'no_activity')
       OR EXISTS (
           SELECT 1 FROM notifications
           WHERE notification_type::text = 'job_idle_reminder'
       ) THEN
        RAISE EXCEPTION 'Downgrade 0616 odmawia: są rekrutacje zamknięte z powodem no_activity albo wpisy job_idle_reminder, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE poza transakcją migracji.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE jobclosereason ADD VALUE IF NOT EXISTS 'no_activity'")
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_idle_reminder'"
        )
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS idle_snoozed_at TIMESTAMPTZ NULL"
    )
    op.execute(
        "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS idle_snoozed_by INTEGER NULL "
        "REFERENCES users(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS idle_snoozed_by")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS idle_snoozed_at")
