"""Powód odrzucenia „Mieszka poza Polską” w każdym szablonie.

Revision ID: 0768_outside_poland_reason
Revises: 0767_contract_engagement_fixed

Decyzja Artura 24.11.2026 (prośba rekrutera, makieta wariant C): system nie
proponuje do żadnej rekrutacji osób mieszkających poza Polską
(``app/services/residence.py``), a w oknie odrzucenia jest powód „Mieszka
poza Polską”, który zapisuje kraj na profilu. Do tej pory takie osoby
odrzucano jako „Inne” (17 z 31 odrzuceń osób spoza UE w 30 dniach).

Wiersz ``outside_poland`` w każdym szablonie, tuż przed „Inne (rejected)”,
jednorazowo przez marker (jak 0745): ta sama instrukcja leci przy każdym
starcie z ``entrypoint.sh`` i bez markera przywracałaby powód skasowany przez
admina. Powód opisuje sytuację, nie osobę — bez weta hiring managera.
Klucz słownika jest też powodem dla systemu, więc migracja odświeża więz
``ck_autofill_feedback_reason``.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0768_outside_poland_reason"
down_revision = "0767_contract_engagement_fixed"
branch_labels = None
depends_on = None

SEED_OUTSIDE_POLAND_REASON = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('outside_poland_reason_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "INSERT INTO rejection_reasons "
    '(template_id, name, category, "order", active, disqualifies_person, '
    "external_source, created_at, updated_at) "
    "SELECT t.id, 'outside_poland', 'rejected'::terminaltype, "
    'COALESCE((SELECT GREATEST(r."order" - 1, 0) FROM rejection_reasons r '
    "WHERE r.template_id = t.id AND r.category::text = 'rejected' "
    "AND r.name = 'Inne (rejected)' LIMIT 1), 99), "
    "TRUE, FALSE, 'manual', NOW(), NOW() "
    "FROM pipeline_templates t "
    "WHERE EXISTS (SELECT 1 FROM marker) "
    "ORDER BY t.id "
    "ON CONFLICT (template_id, name, category) DO NOTHING"
)

_NEW_ROWS = "r.category::text = 'rejected' AND r.name = 'outside_poland'"
REFUSE_WITH_LIVE_ROWS = f"""DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM candidate_stages s
        JOIN rejection_reasons r ON r.id = s.rejection_reason_id
        WHERE {_NEW_ROWS}
    ) OR EXISTS (
        SELECT 1 FROM interview_feedback f
        JOIN rejection_reasons r ON r.id = f.rejection_reason_id
        WHERE {_NEW_ROWS}
    ) THEN
        RAISE EXCEPTION 'Downgrade 0768 odmawia: są wpisy z powodem „Mieszka poza Polską”.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_OUTSIDE_POLAND_REASON)
    for stmt in schema.REASON_CHECK_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Więz powodów dla systemu zostaje szerszy, jak w 0745.
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM rejection_reasons r WHERE {_NEW_ROWS}")
    op.execute("DELETE FROM app_settings WHERE key = 'outside_poland_reason_seeded'")
