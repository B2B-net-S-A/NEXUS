"""P0 — rekrutacja ultrapilna przez 24 h (decyzje Artura 27.10.2026).

Revision ID: 0525_job_p0
Revises: 0524_agreement_admin_details

Prośba Olafa („Omawiane na Daily”), rozwinięta przez Artura: Head of
Recruitment albo admin ustawia rekrutacji P0 na 24 h (48 h albo do piątku),
z powodem, który widzą wszyscy. P0 to nakładka z terminem, nie wartość
``jobs.priority`` — po terminie po prostu przestaje obowiązywać, a zespół nie
przechodzi do „Poprzedni rekruter”.

* ``p0_until`` — do kiedy P0 obowiązuje (pusto = brak P0);
* ``p0_reason`` — po co (do 300 znaków), ``p0_set_at`` / ``p0_set_by``;
* typ dzwonka ``job_p0_set`` (dzwonek i mail obowiązkowy do zespołu).

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0525_job_p0"
down_revision = "0524_agreement_admin_details"
branch_labels = None
depends_on = None

COLUMNS = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_until TIMESTAMPTZ NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_reason VARCHAR(300) NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_set_at TIMESTAMPTZ NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_set_by INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
)
INDEX = (
    "CREATE INDEX IF NOT EXISTS ix_jobs_p0_until ON jobs (p0_until) "
    "WHERE p0_until IS NOT NULL"
)
ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_p0_set'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'job_p0_set'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0525 odmawia: notifications ma wpisy job_p0_set, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in COLUMNS:
        op.execute(statement)
    op.execute(INDEX)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DROP INDEX IF EXISTS ix_jobs_p0_until")
    for column in ("p0_set_by", "p0_set_at", "p0_reason", "p0_until"):
        op.execute(f"ALTER TABLE jobs DROP COLUMN IF EXISTS {column}")
