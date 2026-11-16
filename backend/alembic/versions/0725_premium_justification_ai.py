"""Klucz AI F50: szkic uzasadnienia dopłaty za technologię premium (EN).

Revision ID: 0725_premium_justification_ai
Revises: 0724_order_revenue_steps

Delivery Lead prosi klienta o dopłatę za technologię z umowy ramowej (F3/F4,
Nordea pierwsza) i dziś pisze uzasadnienie po angielsku sam albo z szablonu.
Przycisk „Zaproponuj uzasadnienie” prosi model o szkic z faktów NEXUSA
(``services/premium_skill_justification.py``). Bez nowych tabel: szkic nie
jest zapisywany, DL go poprawia i kopiuje. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0725_premium_justification_ai"
down_revision = "0724_order_revenue_steps"
branch_labels = None
depends_on = None

_KEY = "premium_skill_justification"


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
        RAISE EXCEPTION 'Downgrade 0725 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
