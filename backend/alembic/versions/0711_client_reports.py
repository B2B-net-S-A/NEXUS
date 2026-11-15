"""Katalog raportów klienta: definicje raportów per klient i historia wysyłek.

Revision ID: 0711_client_reports
Revises: 0710_framework_rate_categories

SQL i powody: ``app/services/client_reports_schema.py`` (to samo źródło
czyta ``entrypoint.sh`` przez ``hr_schema_bundle``). Klucz AI
``client_report_requirements`` czyta obowiązki raportowe z fragmentów umów
(przycisk „Znajdź w umowach”). Typ powiadomienia ``client_report_due``
przypomina osobie przygotowującej raport o terminie
(``tasks/client_report_reminders.py``); lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import client_reports_schema as schema

revision = "0711_client_reports"
down_revision = "0710_framework_rate_categories"
branch_labels = None
depends_on = None

_KEY = "client_report_requirements"
_NOTIFICATION_TYPE = "client_report_due"
ADD_NOTIFICATION_TYPE = (
    f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{_NOTIFICATION_TYPE}'"
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
        op.execute(ADD_NOTIFICATION_TYPE)
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )
    for stmt in schema.ALL_DDL:
        op.execute(stmt)


# Wartości enumów zostają po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji ich nie zna — wpis w dzienniku AI albo w powiadomieniach dałby 500
# przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0711 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = '{_NOTIFICATION_TYPE}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0711 odmawia: notifications ma wpisy {_NOTIFICATION_TYPE}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for table in reversed(schema.TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
