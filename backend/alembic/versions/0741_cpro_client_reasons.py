"""Dwa powody klienta z odczytu maili CPro (B7, 19.11.2026).

Revision ID: 0741_cpro_client_reasons
Revises: 0739_contract_rate_documents

Decyzja Artura 19.11.2026: automat poczty CPro wpisuje powód z treści maila
(`services/cpro_reason_map.py`) zamiast „Inne”. Na 108 tekstach z produkcji
dwa powody nie miały odpowiednika na liście: duplikat zgłoszenia od innego
dostawcy (4) i słaba rozmowa u klienta (9).

Każdy szablon, tylko odrzucenie, tuż przed „Inne”, jednorazowo przez marker
(jak 0646 i 0663). Inny dostawca nie jest werdyktem o osobie; słaba rozmowa
jest (``disqualifies_person = true``), bo manager poznał osobę i powiedział nie,
więc uruchamia weto ``hiring_manager_verdicts`` jak ręczne odrzucenie.
Stare wpisy przepina naprawa w ``entrypoint.sh``
(``cpro_rejection_reason_repair``), nie migracja.
"""

from alembic import op

revision = "0741_cpro_client_reasons"
down_revision = "0739_contract_rate_documents"
branch_labels = None
depends_on = None

# ORDER BY: remis kolejności rozstrzyga `id`, więc to on ustala kolejność
# nowych powodów na liście.
SEED_CPRO_CLIENT_REASONS = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('cpro_client_reasons_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "INSERT INTO rejection_reasons "
    '(template_id, name, category, "order", active, disqualifies_person, '
    "external_source, created_at, updated_at) "
    "SELECT t.id, k.name, 'rejected'::terminaltype, "
    'COALESCE((SELECT GREATEST(r."order" - 1, 0) FROM rejection_reasons r '
    "WHERE r.template_id = t.id AND r.category::text = 'rejected' "
    "AND r.name = 'Inne (rejected)' LIMIT 1), 99), "
    "TRUE, k.verdict, 'manual', NOW(), NOW() "
    "FROM pipeline_templates t "
    "CROSS JOIN (VALUES (1, 'client_other_vendor', FALSE), "
    "(2, 'client_interview_weak', TRUE)) AS k(pos, name, verdict) "
    "WHERE EXISTS (SELECT 1 FROM marker) "
    "ORDER BY t.id, k.pos "
    "ON CONFLICT (template_id, name, category) DO NOTHING"
)

# Ruchy z tymi powodami wskazują je kluczem obcym: skasowanie odebrałoby
# historii powód albo wywróciło się na FK.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM candidate_stages s
        JOIN rejection_reasons r ON r.id = s.rejection_reason_id
        WHERE r.name IN ('client_other_vendor', 'client_interview_weak')
    ) OR EXISTS (
        SELECT 1 FROM interview_feedback f
        JOIN rejection_reasons r ON r.id = f.rejection_reason_id
        WHERE r.name IN ('client_other_vendor', 'client_interview_weak')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0741 odmawia: są wpisy z nowymi powodami odrzucenia.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_CPRO_CLIENT_REASONS)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(
        "DELETE FROM rejection_reasons WHERE name IN "
        "('client_other_vendor', 'client_interview_weak')"
    )
    op.execute("DELETE FROM app_settings WHERE key = 'cpro_client_reasons_seeded'")
