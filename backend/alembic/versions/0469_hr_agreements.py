"""„Ludzie w NEXUSIE” — umowy z ludźmi (etap 5, E5).

Revision ID: 0469_hr_agreements
Revises: 0468_hr_documents

Zakres: wzory umów z wersjami (DOCX od Kadr), umowy i aneksy z osobami,
podpis przez Autenti albo ręcznie ze skanem, przepisanie do kartoteki po
podpisie. SQL ma jedno źródło (``app/services/hr_agreements_schema.py``) —
ten sam moduł czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_agreements_schema as schema

revision = "0469_hr_agreements"
down_revision = "0468_hr_documents"
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
        RAISE EXCEPTION 'Downgrade 0469 odmawia: notifications ma wpisy typów umów z ludźmi, których kod sprzed tej rewizji nie odczyta.';
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
