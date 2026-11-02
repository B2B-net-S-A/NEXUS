"""Klucz AI słów z CV wysłanych do wiersza „musi mieć” (F41).

Revision ID: 0634_requirement_word_hints
Revises: 0633_hr_m365_scope_alert

Decyzja Artura z 02.11.2026: przy wierszu „musi mieć”, którego nie ma nikt
z wysłanych, Delivery Lead może poprosić o słowa z ich CV. Wynik nie jest
zapisywany, więc bez nowej tabeli — tylko wartość enumu ``aifeaturekey`` i wiersz
w ``ai_features``; lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0634_requirement_word_hints"
down_revision = "0633_hr_m365_scope_alert"
branch_labels = None
depends_on = None

_KEY = "requirement_word_hints"


def upgrade() -> None:
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
        RAISE EXCEPTION 'Downgrade 0634 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
