"""Klucz AI F58: asystent prawny — propozycje zmian w umowie DOCX.

Revision ID: 0787_legal_redline_ai
Revises: 0786_legal_case_law

Część D planu asystenta prawnego (``docs/asystent-prawny-plan.md``, „Popraw
dokument”): model proponuje zmiany w umowie z powodem i cytatami, kod
sprawdza cytaty i buduje DOCX ze śledzeniem zmian
(``services/legal_redline``). Bez nowych tabel — dokument i zmiany nie są
zapisywane, wynik trafia do Dokumentów kontraktu zwykłym dodaniem pliku.
Numer rewizji spoza tabeli planu (część D miała być bez migracji, ale nowy
klucz AI to wartość enumu); sesja scalająca łańcuchuje ``down_revision``.
Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0787_legal_redline_ai"
down_revision = "0786_legal_case_law"
branch_labels = None
depends_on = None

_KEY = "legal_redline"


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
        RAISE EXCEPTION 'Downgrade 0787 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
