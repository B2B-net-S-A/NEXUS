"""P0: prośba Delivery Leada, zatwierdza Head of Recruitment (decyzja Artura 28.10.2026).

Revision ID: 0610_job_p0_request
Revises: 0609_skill_catalog_identityiq

Propozycja Olafa: Delivery Lead też ma móc oznaczyć rekrutację jako P0.
Decyzja Artura: DL nie ustawia P0 sam, tylko prosi z powodem i czasem,
a Head of Recruitment albo admin zatwierdza albo odrzuca jednym kliknięciem.
Jedna oczekująca prośba na rekrutację:

* ``p0_request_reason`` / ``p0_request_duration`` — z czym DL prosi;
* ``p0_requested_at`` / ``p0_requested_by`` — kiedy i kto (pusto = brak prośby);
* typ dzwonka ``job_p0_requested`` (do Head of Recruitment, mail obowiązkowy).

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0610_job_p0_request"
down_revision = "0609_skill_catalog_identityiq"
branch_labels = None
depends_on = None

COLUMNS = (
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_request_reason VARCHAR(300) NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_request_duration VARCHAR(16) NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_requested_at TIMESTAMPTZ NULL",
    "ALTER TABLE jobs ADD COLUMN IF NOT EXISTS p0_requested_by INTEGER NULL "
    "REFERENCES users(id) ON DELETE SET NULL",
)
ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_p0_requested'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'job_p0_requested'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0610 odmawia: notifications ma wpisy job_p0_requested, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    for statement in COLUMNS:
        op.execute(statement)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for column in (
        "p0_requested_by",
        "p0_requested_at",
        "p0_request_duration",
        "p0_request_reason",
    ):
        op.execute(f"ALTER TABLE jobs DROP COLUMN IF EXISTS {column}")
