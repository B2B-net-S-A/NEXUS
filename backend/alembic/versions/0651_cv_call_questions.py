"""Pytania pod CV w ściądze do rozmowy: tabela i klucz AI F44.

Revision ID: 0651_cv_call_questions
Revises: 0650_manual_placement_exclusions

Decyzja Artura 05.11.2026: przed screeningiem system czyta Profil Championa
i oryginalne CV i podpowiada opcjonalne pytania. DDL
w ``app/services/cv_call_questions_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.cv_call_questions_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0651_cv_call_questions"
down_revision = "0650_manual_placement_exclusions"
branch_labels = None
depends_on = None

_KEY = "cv_call_questions"


def upgrade() -> None:
    for statement in TABLE_DDL:
        op.execute(statement)
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
        RAISE EXCEPTION 'Downgrade 0651 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
