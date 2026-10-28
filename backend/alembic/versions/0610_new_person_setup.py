"""Nowa osoba w NEXUSIE: znacznik „czeka na decyzję” i dzwonek dla HoR i adminów.

Revision ID: 0610_new_person_setup
Revises: 0609_skill_catalog_identityiq

Decyzja Artura z 28.10.2026: po pierwszym logowaniu przez Microsoft Head of
Recruitment i admini dostają dzwonek i mail ``new_person_signed_in``, a osoba
stoi w „Czeka na Ciebie”, dopóki ktoś nie zdecyduje, kim jest. DDL
w ``app/services/new_person_setup_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.new_person_setup_schema import BACKFILL_SQL, COLUMN_DDL, ENUM_DDL

revision = "0610_new_person_setup"
down_revision = "0609_skill_catalog_identityiq"
branch_labels = None
depends_on = None

# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'new_person_signed_in'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0610 odmawia: notifications ma powiadomienia o nowych osobach, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(ENUM_DDL)
    op.execute(COLUMN_DDL)
    op.execute(BACKFILL_SQL)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS setup_pending_since")
