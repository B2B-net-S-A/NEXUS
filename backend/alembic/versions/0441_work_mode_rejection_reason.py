"""Powód „Nie akceptuje trybu pracy” w każdym szablonie procesu.

Revision ID: 0441_work_mode_rejection_reason
Revises: 0440_cv_ready_notification

Decyzja Artura 14.10.2026 (propozycja rekrutera): przy odrzuceniu i przy
rezygnacji kandydata jest powód ``work_mode_mismatch`` („Nie akceptuje trybu
pracy (biuro / hybryda)”). Ruch z tym powodem pyta, ile dni w biurze kandydat
akceptuje, i zapisuje tryb pracy na profilu — wcześniej rekruter wybierał
„Inne” i pisał „zdalnie” w notatce, która nie trafiała ani na profil, ani do
wyszukiwania.

Powód stoi tuż przed „Inne” danego szablonu (ta sama wartość ``order`` co
poprzedni powód; lista sortuje się ``order, id``). Seed jest jednorazowy
przez marker w ``app_settings`` — ta sama instrukcja leci przy każdym starcie
z ``entrypoint.sh`` i bez markera przywracałaby powód skasowany przez admina.
Powód nie jest werdyktem o osobie (``disqualifies_person = false``).
"""

from alembic import op

revision = "0441_work_mode_rejection_reason"
down_revision = "0440_cv_ready_notification"
branch_labels = None
depends_on = None

SEED_WORK_MODE_REASON = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('work_mode_rejection_reason_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "INSERT INTO rejection_reasons "
    '(template_id, name, category, "order", active, disqualifies_person, '
    "external_source, created_at, updated_at) "
    "SELECT t.id, 'work_mode_mismatch', c.cat::terminaltype, "
    'COALESCE((SELECT GREATEST(r."order" - 1, 0) FROM rejection_reasons r '
    "WHERE r.template_id = t.id AND r.category::text = c.cat "
    "AND r.name = 'Inne (' || c.cat || ')' LIMIT 1), 99), "
    "TRUE, FALSE, 'manual', NOW(), NOW() "
    "FROM pipeline_templates t "
    "CROSS JOIN (VALUES ('rejected'), ('withdrawn')) AS c(cat) "
    "WHERE EXISTS (SELECT 1 FROM marker) "
    "ON CONFLICT (template_id, name, category) DO NOTHING"
)

# Ruchy z tym powodem wskazują go kluczem obcym (a rezygnacja MUSI mieć powód,
# CHECK ck_candidate_stages_withdrawn_requires_reason) — skasowanie odebrałoby
# historii powód albo wywróciło się na FK.
REFUSE_WITH_LIVE_ROWS = """DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM candidate_stages s
        JOIN rejection_reasons r ON r.id = s.rejection_reason_id
        WHERE r.name = 'work_mode_mismatch'
    ) THEN
        RAISE EXCEPTION 'Downgrade 0441 odmawia: są ruchy z powodem work_mode_mismatch.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_WORK_MODE_REASON)


def downgrade() -> None:
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute("DELETE FROM rejection_reasons WHERE name = 'work_mode_mismatch'")
    op.execute(
        "DELETE FROM app_settings WHERE key = 'work_mode_rejection_reason_seeded'"
    )
