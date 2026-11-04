"""Klucz AI sprawdzenia zrzutu zgody RODO pod CV (F37).

Revision ID: 0529_consent_screenshot_check
Revises: 0527_jarvis_gaps

Zgłoszenie Martyny 27.10.2026: do CV dla PKO BP trafiały złe zrzuty zgody
(plakat zamiast maila, prośba rekrutera bez odpowiedzi kandydata, zgoda innej
osoby, inny numer ZOB). Model odczytuje zrzut, kod porównuje odczyt z
rekrutacją. Wynik jedzie w pokwitowaniu zgody, więc bez nowej tabeli — tylko
wartość enumu ``aifeaturekey`` i wiersz w ``ai_features``; lustro
w ``entrypoint.sh``.
"""

from alembic import op

revision = "0529_consent_screenshot_check"
down_revision = "0527_jarvis_gaps"
branch_labels = None
depends_on = None

_KEY = "consent_screenshot_check"


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
        RAISE EXCEPTION 'Downgrade 0529 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
