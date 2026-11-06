"""P0 po terminie czeka na decyzję: typ dzwonka ``job_p0_overdue`` (06.11.2026).

Revision ID: 0657_job_p0_overdue
Revises: 0656_client_referral_contract

Prośba Olafa: P0 po terminie nie znika samo, Head of Recruitment potwierdza
koniec albo przedłuża. Sama reguła „trwa po terminie” to kod
(``services/job_p0.is_active``), bez nowych kolumn; migracja dodaje tylko typ
dzwonka, który pętla ``tasks/job_p0_overdue`` wysyła raz na termin.

Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0657_job_p0_overdue"
down_revision = "0656_client_referral_contract"
branch_labels = None
depends_on = None

ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'job_p0_overdue'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'job_p0_overdue'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0657 odmawia: notifications ma wpisy job_p0_overdue, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
