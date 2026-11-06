"""Propozycje do słownika umiejętności: tabela i klucz AI F45.

Revision ID: 0658_skill_proposals
Revises: 0657_job_p0_overdue

Decyzja Artura 06.11.2026 (audyt słownika, „Etap 1: A + B”): co noc model
proponuje hasła i warianty spoza słownika, do słownika wchodzi tylko to, co
zatwierdzi Head of Recruitment albo admin. DDL
w ``app/services/skill_proposals_schema.py``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services.skill_proposals_schema import DOWNGRADE_DDL, TABLE_DDL

revision = "0658_skill_proposals"
down_revision = "0657_job_p0_overdue"
branch_labels = None
depends_on = None

_KEY = "skill_dictionary_proposals"


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
        RAISE EXCEPTION 'Downgrade 0658 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
