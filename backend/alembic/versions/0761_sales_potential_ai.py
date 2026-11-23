"""Klucz AI F54: ocena potencjału firmy w Sprzedaży przed spotkaniem.

Revision ID: 0761_sales_potential_ai
Revises: 0760_novelty_lessons

Decyzja Artura z 23.11.2026 (prompt handlowca ze Sprzedaży, „3 warstwy”): Bot
Research zbiera o firmie zdarzenia, ogłoszenia IT i stos (tryb ``potential``
biegu ``briefing``), a model z rejestru pisze z tego i z bazy wiedzy ocenę
(``services/sales/potential.py``). Bez nowych tabel: research i ocena leżą
w ``sales_bot_results`` (rodzaj ``potential``), baza wiedzy w ``app_settings``.
Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0761_sales_potential_ai"
down_revision = "0760_novelty_lessons"
branch_labels = None
depends_on = None

_KEY = "sales_potential_assessment"


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
        RAISE EXCEPTION 'Downgrade 0761 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
