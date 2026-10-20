"""Klucz AI „terminy rozmowy u klienta z wklejonego maila” (20.10.2026).

Revision ID: 0485_interview_slots_from_mail
Revises: 0484_hm_interviewed_reason

DL wkleja maila od klienta w oknie „Terminy od klienta”, a model wypisuje
terminy z cytatem (``interview_slot_mail``). Trasa niczego nie zapisuje —
terminy idą dalej zwykłym wnioskiem, treść maila nigdzie — więc schemat się
nie zmienia. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0485_interview_slots_from_mail"
down_revision = "0484_hm_interviewed_reason"
branch_labels = None
depends_on = None

_KEY = "interview_slots_from_mail"


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
        RAISE EXCEPTION 'Downgrade 0485 odmawia: ai_usage_log ma wpisy odczytu terminów z maila klienta, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_USAGE)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
