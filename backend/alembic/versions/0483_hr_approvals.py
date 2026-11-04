"""„Ludzie w NEXUSIE” — zgody na wydatki i premie poza umową (decyzja Artura 20.10.2026).

Revision ID: 0483_hr_approvals
Revises: 0482_prep2_skips

Zakres: tabela zgód (``approval_requests``) i dwa dzwonki: zgoda do decyzji
(``hr_approval_requested``) i decyzja do autora (``hr_approval_decided``).
SQL ma jedno źródło (``app/services/hr_approvals_schema.py``) — ten sam moduł
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_approvals_schema as schema

revision = "0483_hr_approvals"
down_revision = "0482_prep2_skips"
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
        RAISE EXCEPTION 'Downgrade 0483 odmawia: notifications ma wpisy typów zgód, których kod sprzed tej rewizji nie odczyta.';
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
