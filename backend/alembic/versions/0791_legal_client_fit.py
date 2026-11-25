"""Zgodność umów B2B z umową ramową klienta (asystent prawny G, 25.11.2026).

Revision ID: 0791_legal_client_fit
Revises: 0790_legal_assistant_tasks

Tabele ``legal_client_fit_checks`` (stan sprawdzenia, jeden wiersz na klienta)
i ``legal_client_fit_findings`` (ustalenie na temat: wymóg klienta z cytatem,
nasz zapis z cytatem albo brak, stan), klucz AI ``legal_client_fit`` (F59)
z zasiewem w ``ai_features``. Same dodania — stary kod działa na nowym
schemacie. DDL ma jedno źródło z siatką w ``entrypoint.sh``
(``services/legal_client_fit/schema.py``). Łańcuch ``down_revision`` z częścią
F poprawia sesja scalająca (plan, „Podział F / G”).
"""

from alembic import op

from app.services.legal_client_fit.schema import ALL_DDL, DOWNGRADE_DDL

revision = "0791_legal_client_fit"
down_revision = "0790_legal_assistant_tasks"
branch_labels = None
depends_on = None

_KEY = "legal_client_fit"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )
    for statement in ALL_DDL:
        op.execute(statement)


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0791 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    for statement in DOWNGRADE_DDL:
        op.execute(statement)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
