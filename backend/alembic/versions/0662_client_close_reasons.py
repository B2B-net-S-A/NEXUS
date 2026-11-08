"""Powody końca procesu u klienta i `ended_by='client_silent'` (08.11.2026).

Zamknięcie rekrutacji z powodem „brak budżetu” kończy pary u klienta powodem
„Request zamknięty”, a brak odpowiedzi klienta przez 30 dni powodem „Klient nie
odpowiedział” z `ended_by='client_silent'`. Obu powodów nie wybiera się ręcznie
w oknie odrzucenia (`reasonFitsEndedBy`). Lustro w `entrypoint.sh`.
"""

from __future__ import annotations

from alembic import op

revision = "0662_client_close_reasons"
down_revision = "0661_cv_title_with_reference"
branch_labels = None
depends_on = None

SEED_CLIENT_CLOSE_REASONS = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('client_close_reasons_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "INSERT INTO rejection_reasons "
    '(template_id, name, category, "order", active, disqualifies_person, '
    "external_source, created_at, updated_at) "
    "SELECT t.id, k.name, 'rejected'::terminaltype, "
    'COALESCE((SELECT GREATEST(r."order" - 1, 0) FROM rejection_reasons r '
    "WHERE r.template_id = t.id AND r.category::text = 'rejected' "
    "AND r.name = 'Inne (rejected)' LIMIT 1), 99), "
    "TRUE, FALSE, 'manual', NOW(), NOW() "
    "FROM pipeline_templates t "
    "CROSS JOIN (VALUES (1, 'request_closed'), (2, 'client_no_response')) "
    "AS k(pos, name) "
    "WHERE EXISTS (SELECT 1 FROM marker) "
    "ORDER BY t.id, k.pos "
    "ON CONFLICT (template_id, name, category) DO NOTHING"
)

ENDED_BY_CHECK = (
    "ALTER TABLE candidate_stages ADD CONSTRAINT ck_candidate_stages_ended_by "
    "CHECK (ended_by IS NULL OR ended_by IN ("
    "'candidate', 'recruiter', 'delivery_lead', 'client', 'client_silent'"
    ")) NOT VALID"
)

REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM candidate_stages s
        JOIN rejection_reasons r ON r.id = s.rejection_reason_id
        WHERE r.name IN ('request_closed', 'client_no_response')
    ) OR EXISTS (
        SELECT 1 FROM candidate_stages WHERE ended_by = 'client_silent'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0662 odmawia: są wpisy z nowymi powodami.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_CLIENT_CLOSE_REASONS)
    op.execute(
        "ALTER TABLE candidate_stages "
        "DROP CONSTRAINT IF EXISTS ck_candidate_stages_ended_by"
    )
    op.execute(ENDED_BY_CHECK)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(
        "DELETE FROM rejection_reasons "
        "WHERE name IN ('request_closed', 'client_no_response')"
    )
    op.execute("DELETE FROM app_settings WHERE key = 'client_close_reasons_seeded'")
    op.execute(
        "ALTER TABLE candidate_stages "
        "DROP CONSTRAINT IF EXISTS ck_candidate_stages_ended_by"
    )
    op.execute(
        "ALTER TABLE candidate_stages ADD CONSTRAINT ck_candidate_stages_ended_by "
        "CHECK (ended_by IS NULL OR ended_by IN ("
        "'candidate', 'recruiter', 'delivery_lead', 'client'"
        ")) NOT VALID"
    )
