"""Opieka po odejściu: pary osoby z wyłączonym kontem → Delivery Lead.

Revision ID: 0620_pair_departure_care
Revises: 0619_announcements

Decyzje Artura 28.10.2026: gdy rekruter odchodzi z firmy (konto wyłączone),
jego żywe pary w otwartych rekrutacjach domyka Delivery Lead rekrutacji —
w ramach obowiązków, bez Ligi, KPI i premii. Tabela ``pair_departure_care``
ma jedno źródło SQL (``app/services/departure_care_schema.py``); entrypoint
wykonuje ``TABLE_DDL`` przy każdym starcie. Typ dzwonka
``departed_pairs_care`` (mail obowiązkowy) — lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import departure_care_schema as schema

revision = "0620_pair_departure_care"
down_revision = "0619_announcements"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        op.execute(schema.ENUM_DDL)


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis tego typu dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'departed_pairs_care'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0620 odmawia: notifications ma wpisy departed_pairs_care, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
