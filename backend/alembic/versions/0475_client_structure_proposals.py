"""„Ludzie w NEXUSIE” — propozycje struktury u klienta („Propozycja automatu + akcept DL”).

Revision ID: 0475_client_structure_proposals
Revises: 0474_tech_card_person

Zakres: pamięć „Pomiń” propozycji menedżera konsultanta i przełożonego osoby
klienta (``client_structure_skips``) i dzwonek ``care_client_structure`` do
Delivery Leadów. SQL ma jedno źródło (``app/services/client_structure_schema.py``)
— ten sam moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import client_structure_schema as schema

revision = "0475_client_structure_proposals"
down_revision = "0474_tech_card_person"
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
        RAISE EXCEPTION 'Downgrade 0475 odmawia: notifications ma wpisy typu struktury u klienta, których kod sprzed tej rewizji nie odczyta.';
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
