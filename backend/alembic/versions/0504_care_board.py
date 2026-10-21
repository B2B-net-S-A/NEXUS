"""„Ludzie w NEXUSIE” — tablica opieki („Do zrobienia”) i popyt dla Delivery Leada.

Revision ID: 0504_care_board
Revises: 0503_b2b_document_participation_types

Zakres: stan kart opieki na tablicy (``care_board_states``), karta
technologiczna z rozmowy (``tech_cards.care_conversation_id``) i dzwonek
``care_demand_signal`` do Delivery Leadów. SQL ma jedno źródło
(``app/services/care_board_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import care_board_schema as schema

revision = "0504_care_board"
down_revision = "0503_b2b_document_participation_types"
branch_labels = None
depends_on = None


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis tego typu dałby 500 przy liście powiadomień.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ({", ".join(f"'{t}'" for t in schema.NOTIFICATION_TYPES)})
    ) THEN
        RAISE EXCEPTION 'Downgrade 0504 odmawia: notifications ma wpisy typu popytu z opieki, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji).
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
