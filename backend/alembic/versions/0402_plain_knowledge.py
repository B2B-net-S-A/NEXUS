"""„Champion po ludzku”: słowniczek, biblioteka ról, teksty rekrutacji (29.09.2026).

Revision ID: 0402_plain_knowledge
Revises: 0401_b2b_annex_rates

Decyzje Artura 29.09.2026 (makiety https://claude.ai/artifact/WEVyKuavTdd8JVggXQ9mD3):
rekruter widzi na górze Podglądu Championa wyjaśnienie „po ludzku”, a w doku
osoby ściągę do rozmowy. Wiedza ogólna (technologie, role, opis klienta) jest
wspólna i zapisana raz; teksty jednej rekrutacji żyją w ``job_plain_briefs``.

DDL ma jedno źródło z entrypointem: ``app/services/plain_knowledge/schema_sql.py``.
Zasiew z plików w repo: ``app/services/plain_knowledge/seed.py``.
"""

from alembic import op

from app.services.plain_knowledge import schema_sql, seed

revision = "0402_plain_knowledge"
down_revision = "0401_b2b_annex_rates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'plain_knowledge_research'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'plain_knowledge_research', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ai_features WHERE feature = 'plain_knowledge_research')"
    )
    for stmt in schema_sql.TABLE_DDL:
        op.execute(stmt)
    seed.seed_sync(op.get_bind())


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis w dzienniku AI dałby 500 w Ustawieniach → AI.
REFUSE_WITH_NEW_ENUM_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_usage_log WHERE feature::text = 'plain_knowledge_research'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0402 odmawia: ai_usage_log ma wpisy plain_knowledge_research, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_NEW_ENUM_ROWS)
    op.execute("DELETE FROM ai_features WHERE feature = 'plain_knowledge_research'")
    for stmt in schema_sql.DROP_DDL:
        op.execute(stmt)
