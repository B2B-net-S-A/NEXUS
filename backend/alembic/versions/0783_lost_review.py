"""Moduł „Przegrane” w Insights: „Co zdecydowało?”, wnioski ze spotkania z DL, klucz AI F56.

Revision ID: 0783_lost_review
Revises: 0782_contract_rate_history_ksef

Decyzja Artura z 25.11.2026: co miesiąc spotkanie z Delivery Leadami
o przegranych rekrutacjach. Dwie nowe tabele (``job_loss_reviews``,
``lost_review_lessons``) i klucz ``lost_review_summary`` (wnioski AI).
SQL: ``app/services/lost_review_schema.py`` (to samo źródło czyta
``entrypoint.sh``). Samo dodanie — stary kod tabel nie zna.
"""

from alembic import op

from app.services import lost_review_schema as schema

revision = "0783_lost_review"
down_revision = "0782_contract_rate_history_ksef"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{schema.AI_FEATURE_KEY}'"
        )
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)
    for stmt in schema.AI_FEATURE_DDL:
        op.execute(stmt)


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{schema.AI_FEATURE_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0783 odmawia: są wpisy {schema.AI_FEATURE_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{schema.AI_FEATURE_KEY}'")
    op.execute("DROP TABLE IF EXISTS lost_review_lessons")
    op.execute("DROP TABLE IF EXISTS job_loss_reviews")
