"""„Klient zaakceptował” — data akceptacji, planowany start i typ dzwonka.

Revision ID: 0451_client_acceptance
Revises: 0450_job_champions

Zgłoszenie Delivery Leada i makiety z decyzjami Artura D1–D6 (16.10.2026):
akceptację klienta oznacza się przyciskiem „Klient zaakceptował” (karta,
panel osoby, werdykt po rozmowie). Ruch na etap „Akceptacja” zapisuje, kiedy
klient zaakceptował (bywa wcześniej niż ruch) i opcjonalnie planowany start —
dwie kolumny wiersza etapu, puste poza etapem ``acceptance``.

Typ dzwonka ``client_accepted`` idzie do rekrutera kandydata, prowadzącego,
Delivery Leada rekrutacji i Head of Recruitment (kategoria „Akceptacje
klienta”, nie do wyciszenia).

Lustro w ``entrypoint.sh`` — pilnuje ``test_client_acceptance_migration.py``.
"""

from alembic import op

revision = "0451_client_acceptance"
down_revision = "0450_job_champions"
branch_labels = None
depends_on = None

ADD_ACCEPTED_ON = (
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS client_accepted_on DATE NULL"
)
ADD_PLANNED_START = (
    "ALTER TABLE candidate_stages ADD COLUMN IF NOT EXISTS planned_start_on DATE NULL"
)
ADD_NOTIFICATION_TYPE = (
    "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS 'client_accepted'"
)

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — dzwonek tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'client_accepted'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0451 odmawia: notifications ma wpisy client_accepted, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(ADD_ACCEPTED_ON)
    op.execute(ADD_PLANNED_START)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ADD_NOTIFICATION_TYPE)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS planned_start_on")
    op.execute("ALTER TABLE candidate_stages DROP COLUMN IF EXISTS client_accepted_on")
