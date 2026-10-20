"""Powód „Już po rozmowie u tego hiring managera” w każdym szablonie procesu.

Revision ID: 0484_hm_interviewed_reason
Revises: 0483_hr_approvals

20.10.2026: Delivery Lead odrzucał osobę, bo była już na rozmowie u managera
tej rekrutacji w innym procesie. Słownik tego nie miał, a przy „Inne” nie było
gdzie napisać dlaczego — w historii zostawało samo „Inne”. Ruch z tym powodem
wymaga opisu (która rozmowa, kiedy), jak „Inne”.

Tylko odrzucenie (rezygnacja to decyzja kandydata, nie managera). Powód stoi
tuż przed „Inne” szablonu, jak 0442. Seed jednorazowy przez marker
w ``app_settings`` — ta sama instrukcja leci przy każdym starcie
z ``entrypoint.sh`` i bez markera przywracałaby powód skasowany przez admina.
Powód nie jest werdyktem o osobie (``disqualifies_person = false``): mówi, że
ten manager już ją zna, a nie że ją odrzucił.
"""

from alembic import op

revision = "0484_hm_interviewed_reason"
down_revision = "0483_hr_approvals"
branch_labels = None
depends_on = None

SEED_HM_INTERVIEWED_REASON = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('hm_interviewed_rejection_reason_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "INSERT INTO rejection_reasons "
    '(template_id, name, category, "order", active, disqualifies_person, '
    "external_source, created_at, updated_at) "
    "SELECT t.id, 'hm_already_interviewed', 'rejected'::terminaltype, "
    'COALESCE((SELECT GREATEST(r."order" - 1, 0) FROM rejection_reasons r '
    "WHERE r.template_id = t.id AND r.category::text = 'rejected' "
    "AND r.name = 'Inne (rejected)' LIMIT 1), 99), "
    "TRUE, FALSE, 'manual', NOW(), NOW() "
    "FROM pipeline_templates t "
    "WHERE EXISTS (SELECT 1 FROM marker) "
    "ON CONFLICT (template_id, name, category) DO NOTHING"
)

# Ruchy z tym powodem wskazują go kluczem obcym — skasowanie odebrałoby
# historii powód albo wywróciło się na FK.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM candidate_stages s
        JOIN rejection_reasons r ON r.id = s.rejection_reason_id
        WHERE r.name = 'hm_already_interviewed'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0484 odmawia: są ruchy z powodem hm_already_interviewed.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_HM_INTERVIEWED_REASON)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DELETE FROM rejection_reasons WHERE name = 'hm_already_interviewed'")
    op.execute(
        "DELETE FROM app_settings WHERE key = 'hm_interviewed_rejection_reason_seeded'"
    )
