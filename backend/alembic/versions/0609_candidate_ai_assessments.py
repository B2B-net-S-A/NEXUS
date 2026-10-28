"""„Oceń z AI” na zaznaczonych osobach: tabela ocen i klucz AI F39.

Revision ID: 0609_candidate_ai_assessments
Revises: 0608_linkedin_extension

Decyzja Artura 28.10.2026 (makieta C): rekruter zaznacza osoby w oknie
„Kandydaci do dodania” i dostaje Dzwoń / Może / Nie pasuje z cytatem z CV,
zamiast pobierać CV do prywatnego czatu. SQL tabeli ma jedno źródło
(``app/services/candidate_ai_assessment_schema.py``); entrypoint wykonuje
``TABLE_DDL`` przy każdym starcie. Klucz AI F39 (``candidate_ai_assessment``)
— wartość enumu i wiersz w ``ai_features``, lustro w ``entrypoint.sh``.
"""

from alembic import op

from app.services import candidate_ai_assessment_schema as schema

revision = "0609_candidate_ai_assessments"
down_revision = "0608_linkedin_extension"
branch_labels = None
depends_on = None

_KEY = "candidate_ai_assessment"


def upgrade() -> None:
    for stmt in schema.TABLE_DDL:
        op.execute(stmt)
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
        RAISE EXCEPTION 'Downgrade 0609 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    op.execute("DROP TABLE IF EXISTS candidate_ai_assessments")
