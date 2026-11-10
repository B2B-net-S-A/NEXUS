"""„Kto już to robił”: tabele wyszukiwania po celu i klucze AI F46/F47.

Revision ID: 0677_duty_search
Revises: 0676_sales_signal_runs

Decyzja Artura 09.11.2026: wyszukiwanie po celu projektu i obowiązkach, gdy
nie znamy technologii krytycznych (reguła
``docs/claude/kandydaci-wyszukiwanie/kto-juz-to-robil-wyszukiwanie-po-celu.md``).
SQL tabel ma jedno źródło (``app/services/duty_search_schema.py``); entrypoint
wykonuje ``TABLE_DDL`` przy każdym starcie. Klucze AI: ``duty_search_plan``
(rozbicie celu) i ``duty_search_judge`` (ocena CV z cytatem) — wartości enumu
i wiersze w ``ai_features``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import duty_search_schema as schema

revision = "0677_duty_search"
down_revision = "0676_sales_signal_runs"
branch_labels = None
depends_on = None

_KEYS = ("duty_search_plan", "duty_search_judge")


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)
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


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log
               WHERE feature::text IN ('duty_search_plan', 'duty_search_judge')) THEN
        RAISE EXCEPTION 'Downgrade 0677 odmawia: są wpisy duty_search_*, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for key in _KEYS:
        op.execute(f"DELETE FROM ai_features WHERE feature = '{key}'")
    for stmt in schema.DOWNGRADE_DDL:
        op.execute(stmt)
