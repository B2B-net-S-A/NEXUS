"""Bliźniacze rekrutacje: rodzaj połączenia, pary pytań, odrzucone pary.

Revision ID: 0614_job_twins
Revises: 0613_timesheets_permission

Decyzje Artura z 28.10.2026: Delivery Lead łączy swoje otwarte rekrutacje,
Head of Recruitment i admin dowolne, także między klientami. Bliźniak to
``job_similar_links.kind = 'twin'`` z parami pytań screeningowych
(``question_pairs``); osoba przechodzi na „Zweryfikowany” po screeningu pod
wszystkie bliźniaki. DDL w ``app/services/job_twin_schema.py``, lustro
w ``entrypoint.sh``.
"""

from alembic import op

from app.services.job_twin_schema import ALL_DDL, ENUM_DDL

revision = "0614_job_twins"
down_revision = "0613_timesheets_permission"
branch_labels = None
depends_on = None

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'job_twin_linked'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0614 odmawia: notifications ma dzwonki o bliźniakach, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ENUM_DDL)
    for statement in ALL_DDL:
        op.execute(statement)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DROP TABLE IF EXISTS job_twin_dismissals")
    op.execute("DROP INDEX IF EXISTS ix_job_similar_links_twins")
    op.execute(
        "ALTER TABLE job_similar_links DROP CONSTRAINT IF EXISTS ck_job_similar_links_kind"
    )
    op.execute("ALTER TABLE job_similar_links DROP COLUMN IF EXISTS question_pairs")
    op.execute("ALTER TABLE job_similar_links DROP COLUMN IF EXISTS kind")
