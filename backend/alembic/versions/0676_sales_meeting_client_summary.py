"""Sprzedaż: podsumowanie spotkania dla klienta i wysyłka z NEXUSA.

Revision ID: 0676_sales_meeting_client_summary
Revises: 0675_notification_on_behalf

DDL w ``app/services/sales_schema.py`` (``CLIENT_SUMMARY_DDL``; to samo źródło
czyta ``entrypoint.sh``). Klucz AI F46 (``sales_meeting_client_summary``).
"""

from alembic import op

from app.services import sales_schema as schema

revision = "0676_sales_meeting_client_summary"
down_revision = "0675_notification_on_behalf"
branch_labels = None
depends_on = None

_KEY = "sales_meeting_client_summary"


def upgrade() -> None:
    for stmt in schema.CLIENT_SUMMARY_DDL:
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
        RAISE EXCEPTION 'Downgrade 0676 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for stmt in schema.CLIENT_SUMMARY_DOWNGRADE_DDL:
        op.execute(stmt)
