"""„Ludzie w NEXUSIE” — rozliczenia zespołu (etap 4, R1–R12).

Revision ID: 0467_hr_settlements
Revises: 0466_care_announcements

Zakres: dane do rozliczeń osoby (NIP, wykaz VAT, rachunek zaszyfrowany,
identyfikator w Symfonii), rozliczenia zamkniętego miesiąca, faktury od osób
(KSeF albo PDF) i zdarzenia płatności. SQL ma jedno źródło
(``app/services/hr_settlement_schema.py``) — ten sam moduł czyta
``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_settlement_schema as schema

revision = "0467_hr_settlements"
down_revision = "0466_care_announcements"
branch_labels = None
depends_on = None


# Wartość enuma zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis tego typu dałby 500 przy dzwonku.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text IN ({", ".join(f"'{t}'" for t in schema.NOTIFICATION_TYPES)})
    ) THEN
        RAISE EXCEPTION 'Downgrade 0467 odmawia: notifications ma wpisy typów rozliczeń, których kod sprzed tej rewizji nie odczyta.';
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
