"""Zgłoszenia z linku rekrutacji przegląda AI przed „Nowi” (29.09.2026).

Revision ID: 0404_application_screenings
Revises: 0403_plain_knowledge

Decyzje Artura 29.09.2026: zgłoszenie z ``/r/<slug>`` (link ``kind='job'``)
nie otwiera procesu w requeście. Zapisuje się kandydat, CV, zgoda, źródło
i wiersz ``application_screenings`` (``pending``); pętla w tle ocenia CV
(kod: must-have i bramki twarde, GPT-6 Luna: uzasadnienie z cytatem)
i dopiero wtedy dodaje osobę do „Nowi” albo zostawia ją w bazie na liście
„Odrzuceni przez AI”.

DDL ma jedno źródło z entrypointem: ``app/services/application_screening_schema.py``.
"""

from alembic import op

from app.services import application_screening_schema as schema

revision = "0404_application_screenings"
down_revision = "0403_plain_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'application_screening'"
        )
        op.execute(
            "ALTER TYPE notificationtype ADD VALUE IF NOT EXISTS "
            "'application_screening_digest'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'application_screening', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ai_features WHERE feature = 'application_screening')"
    )
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)


# Wartości enumów zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — wpis w dzienniku AI albo w powiadomieniach
# dałby 500. Oczekujące oceny to osoby, które nie trafiły jeszcze do „Nowi”:
# DROP TABLE zostawiłby je bez procesu i bez śladu.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_usage_log WHERE feature::text = 'application_screening'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0404 odmawia: ai_usage_log ma wpisy application_screening, których kod sprzed tej rewizji nie odczyta.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM notifications
        WHERE notification_type::text = 'application_screening_digest'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0404 odmawia: notifications ma wpisy application_screening_digest, których kod sprzed tej rewizji nie odczyta.';
    END IF;
    IF to_regclass('application_screenings') IS NOT NULL THEN
        IF EXISTS (SELECT 1 FROM application_screenings) THEN
            RAISE EXCEPTION 'Downgrade 0404 odmawia: application_screenings ma wiersze (oczekujące zgłoszenia i odrzuceni przez AI).';
        END IF;
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DELETE FROM ai_features WHERE feature = 'application_screening'")
    for stmt in schema.DROP_DDL:
        op.execute(stmt)
