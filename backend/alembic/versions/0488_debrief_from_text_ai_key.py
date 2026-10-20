"""Klucz AI „Po rozmowie — pytania i oferta z notatki z telefonu” (20.10.2026).

Revision ID: 0488_debrief_from_text
Revises: 0487_slot_choice_client_reply

Rekruter wkleja albo pisze w trakcie telefonu, co mówił kandydat po rozmowie
u klienta, a model rozpisuje pytania klienta, gotowość do oferty i stawkę
z cytatem (``debrief_from_text``). Trasa niczego nie zapisuje — zapis to
zwykły debrief — więc schemat się nie zmienia. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0488_debrief_from_text"
down_revision = "0487_slot_choice_client_reply"
branch_labels = None
depends_on = None

_KEY = "debrief_from_text"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod sprzed
# tej rewizji jej nie zna — wpis w dzienniku AI dałby 500.
REFUSE_WITH_USAGE = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0488 odmawia: ai_usage_log ma wpisy odczytu notatki po rozmowie, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_USAGE)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
