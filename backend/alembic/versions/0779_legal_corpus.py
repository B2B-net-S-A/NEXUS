"""Asystent prawny, część A: korpus prawa i klucz AI ``legal_assistant`` (F56).

Revision ID: 0779_legal_corpus
Revises: 0778_b2b_document_preliminary_jdg

Decyzja Artura z 25.11.2026 (asystent prawny w tle istniejących ekranów,
``docs/asystent-prawny-plan.md``). Tabele ``legal_acts``,
``legal_act_versions`` i ``legal_provisions``: SQL i powody w
``app/services/legal/schema.py`` (to samo źródło czyta ``entrypoint.sh`` przez
``hr_schema_bundle``). Klucz ``legal_assistant`` w ``aifeaturekey`` z wierszem
w ``ai_features`` (lustro w ``entrypoint.sh``).

Sesja główna planu łańcuchuje migracje części A–H przy scalaniu (każda część
startuje od 0778). Reguły: ``docs/claude/asystent-prawny/``.
"""

from alembic import op

from app.services.legal import schema

revision = "0779_legal_corpus"
down_revision = "0778_b2b_document_preliminary_jdg"
branch_labels = None
depends_on = None

_KEY = "legal_assistant"


def upgrade() -> None:
    for stmt in schema.ALL_DDL:
        op.execute(stmt)
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0779 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
