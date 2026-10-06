"""Karta rekomendacji z notatki rekrutera i „Ułóż w zdanie” (06.10.2026).

Revision ID: 0421_recommendation_card_assist
Revises: 0420_job_budget_hourly_min

Dwa klucze AI (GPT-6 Luna): ``recommendation_card_note_read`` — odczyt
notatki wgranej albo wklejonej w oknie karty, ``screening_answer_phrasing`` —
hasła rekrutera w pełnym zdaniu. Schemat karty i arkusza się nie zmienia
(JSONB). Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0421_recommendation_card_assist"
down_revision = "0420_job_budget_hourly_min"
branch_labels = None
depends_on = None

_KEYS = ("recommendation_card_note_read", "screening_answer_phrasing")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for key in _KEYS:
            op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{key}'")
    for key in _KEYS:
        op.execute(
            "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
            f"SELECT '{key}', TRUE, 0, NOW(), NOW() "
            "WHERE NOT EXISTS "
            f"(SELECT 1 FROM ai_features WHERE feature = '{key}')"
        )


# Wartości enumu zostają po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji ich nie zna — wpis w dzienniku AI dałby 500.
REFUSE_WITH_USAGE = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_usage_log
        WHERE feature::text IN ('recommendation_card_note_read', 'screening_answer_phrasing')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0421 odmawia: ai_usage_log ma wpisy kart z notatki albo „Ułóż w zdanie”, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_USAGE)
    op.execute(
        "DELETE FROM ai_features WHERE feature IN "
        "('recommendation_card_note_read', 'screening_answer_phrasing')"
    )
