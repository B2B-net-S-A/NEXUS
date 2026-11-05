"""Sześć powodów odrzucenia, które zespół wpisywał ręcznie pod „Inne”.

Revision ID: 0646_frequent_rejection_reasons
Revises: 0645_back_office_role

04.11.2026 (decyzja Artura): od 12.10 696 z 1808 odrzuceń to „Inne”, a 584
z nich opisał człowiek, powtarzając te same powody. Wybór z listy zastępuje
pisanie, a raporty pokazują prawdziwe przyczyny.

Każdy szablon, tylko odrzucenie, tuż przed „Inne” (jak 0484). Seed jednorazowy
przez marker w ``app_settings``: ta sama instrukcja leci przy każdym starcie
z ``entrypoint.sh`` i bez markera przywracałaby powód skasowany przez admina.
Żaden nie jest werdyktem o osobie (``disqualifies_person = false``): opisują
sytuację, więc nie uruchamiają weta z ``hiring_manager_verdicts``. Starych
wpisów migracja nie zmienia.
"""

from alembic import op

revision = "0646_frequent_rejection_reasons"
down_revision = "0645_back_office_role"
branch_labels = None
depends_on = None

REASON_KEYS = (
    "not_looking_for_work",
    "client_conflict",
    "contract_form",
    "no_contact",
    "client_no_reason",
    "client_chose_other",
)

# ORDER BY: remis kolejności rozstrzyga `id`, więc to on ustala kolejność
# nowych powodów na liście.
SEED_FREQUENT_REJECTION_REASONS = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('frequent_rejection_reasons_seeded', 'true'::jsonb) "
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
    "CROSS JOIN (VALUES (1, 'not_looking_for_work'), (2, 'client_conflict'), "
    "(3, 'contract_form'), (4, 'no_contact'), (5, 'client_no_reason'), "
    "(6, 'client_chose_other')) AS k(pos, name) "
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
        WHERE r.name IN ('not_looking_for_work', 'client_conflict', 'contract_form',
                         'no_contact', 'client_no_reason', 'client_chose_other')
    ) OR EXISTS (
        SELECT 1 FROM interview_feedback f
        JOIN rejection_reasons r ON r.id = f.rejection_reason_id
        WHERE r.name IN ('not_looking_for_work', 'client_conflict', 'contract_form',
                         'no_contact', 'client_no_reason', 'client_chose_other')
    ) THEN
        RAISE EXCEPTION 'Downgrade 0646 odmawia: są wpisy z nowymi powodami odrzucenia.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_FREQUENT_REJECTION_REASONS)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(
        "DELETE FROM rejection_reasons WHERE name IN ("
        "'not_looking_for_work', 'client_conflict', 'contract_form', "
        "'no_contact', 'client_no_reason', 'client_chose_other')"
    )
    op.execute(
        "DELETE FROM app_settings WHERE key = 'frequent_rejection_reasons_seeded'"
    )
