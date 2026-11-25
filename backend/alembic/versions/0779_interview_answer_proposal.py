"""Propozycje odpowiedzi w „Pytaniach z rozmów”: źródło odpowiedzi i klucz AI F55.

Revision ID: 0779_interview_answer_proposal
Revises: 0778_b2b_document_preliminary_jdg

Decyzja Artura z 25.11.2026: pod każdym pytaniem z banku klienta stoi
proponowana odpowiedź. Odpowiedź leży jak dotąd w ``interview_questions.
ideal_answer``, a nowa kolumna ``ideal_answer_source`` mówi, skąd jest:
``excel`` (archiwum Excela), ``manual`` (wpisana przez człowieka), ``ai``
(nocny bieg F55, ``services/interview_answer_proposals.py``) albo ``none``
(model uznał wiersz za nagłówek sekcji, nie pytanie — bez odpowiedzi i bez
ponownej wysyłki co noc). Backfill: odpowiedzi sprzed tej rewizji to ``excel``
przy ``legacy_import`` i ``manual`` przy reszcie.

Samo dodanie kolumny NULL i nowej wartości enuma — stary kod ich nie zna.
Lustro w ``entrypoint.sh``.
"""

from alembic import op

revision = "0779_interview_answer_proposal"
down_revision = "0778_b2b_document_preliminary_jdg"
branch_labels = None
depends_on = None

_KEY = "interview_answer_proposal"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS '{_KEY}'")
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        f"SELECT '{_KEY}', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        f"(SELECT 1 FROM ai_features WHERE feature = '{_KEY}')"
    )
    op.execute(
        "ALTER TABLE interview_questions "
        "ADD COLUMN IF NOT EXISTS ideal_answer_source VARCHAR(16) NULL"
    )
    op.execute(
        "UPDATE interview_questions SET ideal_answer_source = CASE "
        "WHEN source = 'legacy_import' THEN 'excel' ELSE 'manual' END "
        "WHERE ideal_answer_source IS NULL "
        "AND NULLIF(btrim(ideal_answer), '') IS NOT NULL"
    )


# Wartość enumu zostaje po downgrade (Postgres nie ma DROP VALUE), a kod
# sprzed tej rewizji jej nie zna — wpis w logu użycia dałby 500 przy odczycie.
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM ai_usage_log WHERE feature::text = '{_KEY}') THEN
        RAISE EXCEPTION 'Downgrade 0779 odmawia: są wpisy {_KEY}, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM ai_features WHERE feature = '{_KEY}'")
    op.execute(
        "ALTER TABLE interview_questions DROP COLUMN IF EXISTS ideal_answer_source"
    )
