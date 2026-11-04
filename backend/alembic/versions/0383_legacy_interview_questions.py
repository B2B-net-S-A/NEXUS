"""Archiwum pytań z interview: źródło `legacy_import` i klucz AI importu (25.09.2026).

Revision ID: 0383_legacy_interview_questions
Revises: 0382_nordea_invoice_lines

Rekruterzy przez lata zapisywali w Excelu, o co klient pytał kandydata na
rozmowie. Skrypt ``scripts/import_legacy_interview_questions.py`` wgrywa te
pytania do banku ``interview_questions`` ze źródłem ``legacy_import``.
Osobna wartość, a nie ``client_debrief``: listy „najnowsze N pytań klienta”
(prep, ocena prepu, Luna na ``/jobs/new``) czytają wyłącznie debriefy, więc
archiwum dociera do rekrutacji tylko po roli (``client_question_archive``).

Wartości enumów nie są usuwane przy downgrade (Postgres nie ma DROP VALUE).
Lustro w ``entrypoint.sh`` — pilnuje ``test_client_question_archive.py``
i ``test_ai_feature_enum_entrypoint_mirror.py``.
"""

from alembic import op

revision = "0383_legacy_interview_questions"
down_revision = "0382_nordea_invoice_lines"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE interviewquestionsource ADD VALUE IF NOT EXISTS 'legacy_import'"
        )
        op.execute(
            "ALTER TYPE aifeaturekey ADD VALUE IF NOT EXISTS 'interview_question_import'"
        )
    op.execute(
        "INSERT INTO ai_features (feature, enabled, monthly_limit, created_at, updated_at) "
        "SELECT 'interview_question_import', TRUE, 0, NOW(), NOW() "
        "WHERE NOT EXISTS "
        "(SELECT 1 FROM ai_features WHERE feature = 'interview_question_import')"
    )


# Runda 8 (R8-N15-2): wartości enumów zostają po downgrade, a kod sprzed tej
# rewizji ich nie zna — ORM rzuca `LookupError` (500) na pytaniu z archiwum
# (prep-kit, bank pytań) i na wpisie w dzienniku AI (raport w Ustawieniach).
# Downgrade odmawia, zamiast kasować archiwum pytań i historię kosztów.
REFUSE_WITH_NEW_ENUM_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM interview_questions WHERE source::text = 'legacy_import'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0383 odmawia: interview_questions ma pytania z archiwum (legacy_import). Cofnij import skryptem import_legacy_interview_questions.py --rollback albo zostaw tę rewizję.';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ai_usage_log WHERE feature::text = 'interview_question_import'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0383 odmawia: ai_usage_log ma wpisy interview_question_import, których kod sprzed tej rewizji nie odczyta.';
    END IF;
END $$"""


def downgrade() -> None:
    op.execute(REFUSE_WITH_NEW_ENUM_ROWS)
    op.execute("DELETE FROM ai_features WHERE feature = 'interview_question_import'")
