"""„Ludzie w NEXUSIE” — rozliczenie zgód w Finansach (etap 3, decyzje Artura 20.10.2026).

Revision ID: 0486_approval_settlement
Revises: 0485_interview_slots_from_mail

Zakres: dokumenty wydatków (faktura albo paragon do zgody, faktury kosztowe
z KSeF z samych metadanych), lista sprzedawców „stały koszt”, kolumny
rozliczenia na ``approval_requests``, dwa dzwonki (dopłata do zatwierdzającego,
odnowienie subskrypcji do opiekuna) i klucz AI odczytu dokumentu. SQL ma jedno
źródło (``app/services/hr_approval_settlement_schema.py``) — ten sam moduł
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``.
"""

from alembic import op

from app.services import hr_approval_settlement_schema as schema

revision = "0486_approval_settlement"
down_revision = "0485_interview_slots_from_mail"
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
        RAISE EXCEPTION 'Downgrade 0486 odmawia: notifications ma wpisy typów rozliczenia zgód, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""

# Klucz AI zostaje w enumie po downgrade, a dziennik AI sprzed tej rewizji go
# nie odczyta (wzór 0485, audyt 22.10.2026).
REFUSE_WITH_USAGE = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_usage_log WHERE feature::text = 'expense_document_read'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0486 odmawia: ai_usage_log ma wpisy odczytu dokumentów wydatków, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def upgrade() -> None:
    # ADD VALUE wymaga autocommitu (nie może żyć w transakcji migracji), a seed
    # ai_features używa nowej etykiety jako literału.
    with op.get_context().autocommit_block():
        for stmt in schema.ENUM_DDL:
            op.execute(stmt)
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'expense_document_read'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'expense_document_read', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM ai_features WHERE feature = 'expense_document_read')"
    )
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(REFUSE_WITH_USAGE)
    op.execute("DELETE FROM ai_features WHERE feature = 'expense_document_read'")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
