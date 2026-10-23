"""Raport „Jakość podpowiedzi systemu” — tabela, klucz AI i typ dzwonka.

Revision ID: 0518_autofill_quality_report
Revises: 0517_autofill_decisions_due_notification

Decyzja Artura 23.10.2026 (silnik „Nowi na 20”): ekran z liczbami odrzuceń
osób od systemu i raport co poniedziałek z 3–5 propozycjami poprawek. Tabela
ma jedno źródło (``app/services/autofill_quality_schema.py``); klucz AI
``autofill_quality_report`` z wierszem w ``ai_features`` i wartość
``notificationtype`` — lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import autofill_quality_schema as schema

revision = "0518_autofill_quality_report"
down_revision = "0517_autofill_decisions_due_notification"
branch_labels = None
depends_on = None

_KEY = "autofill_quality_report"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
        op.execute(f"ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


# Wartości enumów zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — wpis dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}')
       OR EXISTS (
           SELECT 1 FROM notifications WHERE notification_type::text = '{_KEY}'
       ) THEN
        RAISE EXCEPTION 'Downgrade 0518 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
