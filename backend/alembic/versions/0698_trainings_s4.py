"""Szkolenia S4: rozdziały i podsumowanie AI, próba techniczna, obowiązkowe dla roli, tematy.

Revision ID: 0698_trainings_s4
Revises: 0697_training_teams

SQL i powody: ``app/services/trainings_schema.py`` (``S4_DDL``; to samo źródło czyta
``entrypoint.sh`` przez ``hr_schema_bundle``). Klucz AI F49
(``training_transcript_summary``).
"""

from alembic import op

from app.services import trainings_schema as schema

revision = "0698_trainings_s4"
down_revision = "0697_training_teams"
branch_labels = None
depends_on = None

_KEY = schema.AI_SUMMARY_FEATURE


def upgrade() -> None:
    for stmt in schema.S4_DDL:
        op.execute(stmt)
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed tej
# rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0698 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for table in reversed(schema.S4_TABLES):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    for table, columns in schema.S4_COLUMNS.items():
        for column in columns:
            op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
