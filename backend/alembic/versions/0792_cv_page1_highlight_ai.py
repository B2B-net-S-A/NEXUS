"""Klucz AI F61: propozycja wyróżnika pod nazwiskiem w „Nowym CV”.

Revision ID: 0792_cv_page1_highlight_ai
Revises: 0791_legal_client_fit

Decyzja Artura z 26.11.2026: wyróżnik strony 1 ma trzy źródła — praca u
klienta (automat), propozycja AI przyjęta przez rekrutera i wpis rekrutera.
Model proponuje nagrodę, wyróżnienie albo certyfikat z MUST z cytatem z CV,
kod sprawdza cytat (``services/cv_page1_highlight_checks.py``). Bez nowych
tabel — propozycje leżą w ``candidate_stage_cvs.page1_extras``. Same dodania,
stary kod działa na nowym schemacie. Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0792_cv_page1_highlight_ai"
down_revision = "0791_legal_client_fit"
branch_labels = None
depends_on = None

_KEY = "cv_page1_highlight"


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
        RAISE EXCEPTION 'Downgrade 0792 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
