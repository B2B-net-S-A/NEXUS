"""Rozmowa u klienta bez Prepu 2 — wyjątek z powodem i telefonem przed rozmową.

Revision ID: 0480_prep2_skips
Revises: 0479_equipment_return_reminder

Zgłoszenie rekrutera (20.10.2026): zdarza się, że kandydat nie znajdzie czasu
na drugi prep przed rozmową u klienta. Decyzja Artura: pominięcie jest
wyjątkiem, nie wyborem — tylko tuż przed rozmową, po odbytym Prepie 1,
z powodem i z krótkim telefonem do kandydata. Jeden wpis na rozmowę
(``interview_event_id`` UNIQUE).

Dwa typy powiadomień w ikonie „Kalendarz”: pominięcie (do Delivery Leada
rekrutacji) i przekroczony próg pominięć (do Head of Recruitment).

Lustro w ``entrypoint.sh`` — pilnuje ``test_prep2_skip_migration.py``.
"""

from alembic import op

revision = "0480_prep2_skips"
down_revision = "0479_equipment_return_reminder"
branch_labels = None
depends_on = None

CREATE_TABLE = """CREATE TABLE IF NOT EXISTS prep2_skips (
    id BIGSERIAL PRIMARY KEY,
    interview_event_id INTEGER NOT NULL UNIQUE
        REFERENCES calendar_events(id) ON DELETE CASCADE,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    reason VARCHAR(20) NOT NULL,
    reason_note TEXT NULL,
    call_at TIMESTAMPTZ NOT NULL,
    call_done_at TIMESTAMPTZ NULL,
    call_done_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    call_note TEXT NULL,
    created_by INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_prep2_skips_reason
        CHECK (reason IN ('no_slot','short_notice','prep1_covered','other')),
    CONSTRAINT ck_prep2_skips_other_note
        CHECK (reason <> 'other' OR reason_note IS NOT NULL)
)"""
CREATE_INDEX = "CREATE INDEX IF NOT EXISTS ix_prep2_skips_pair ON prep2_skips (candidate_id, job_id)"

NOTIFICATION_TYPES = ("prep2_skipped", "prep2_skip_threshold")
ADD_NOTIFICATION_TYPES = tuple(
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{value}'"
    for value in NOTIFICATION_TYPES
)

# Wartości enuma zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — powiadomienie takiego typu dałoby 500.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ('prep2_skipped', 'prep2_skip_threshold')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0480 odmawia: notifications ma wpisy o pominiętym Prepie 2, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(CREATE_TABLE)
    op.execute(CREATE_INDEX)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        for statement in ADD_NOTIFICATION_TYPES:
            op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DROP TABLE IF EXISTS prep2_skips")
