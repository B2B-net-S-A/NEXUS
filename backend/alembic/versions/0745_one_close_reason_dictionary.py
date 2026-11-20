"""Jeden słownik powodów zamknięcia procesu: brakujące powody w szablonach.

Revision ID: 0745_one_close_reason_dictionary
Revises: 0744_b2b_document_preliminary_b2b

Decyzja Artura 19.11.2026 (wariant A makiety „Zamknij proces”): okno pyta
o powód z jednego słownika (``app/services/close_reasons.py``), a każdy powód
słownika ma własny klucz w szablonie. Dotąd 8 z 19 powodów okna „Nowych” /
„Screeningu” lądowało jako „Inne” z nazwą w opisie, a rezygnacja miała osobną
listę bez form umowy, „Nie szuka” i braku kontaktu.

Każdy szablon, tuż przed „Inne” tej samej kategorii, jednorazowo przez marker
(jak 0442, 0646 i 0740): ta sama instrukcja leci przy każdym starcie
z ``entrypoint.sh`` i bez markera przywracałaby powód skasowany przez admina.
Klucz słownika jest też powodem dla systemu, więc migracja odświeża więz
``ck_autofill_feedback_reason``. Werdyktem o osobie (weto ``hiring_manager_verdicts``) są tylko brak polskiego
i słaby angielski, jak „Brak doświadczenia”. Starych wpisów migracja nie
przepina; stare nazwy dostają etykiety słownika przy odczycie.
"""

from alembic import op

from app.services import autofill_feedback_schema as schema

revision = "0745_one_close_reason_dictionary"
down_revision = "0744_b2b_document_preliminary_b2b"
branch_labels = None
depends_on = None

REJECTED_KEYS = (
    "client_project_closed",
    "client_after_deadline",
    "overqualified",
    "other_level_or_role",
    "no_polish",
    "weak_english",
    "available_too_late",
    "in_other_process",
    "client_refused",
    "outdated_cv",
    "profile_mismatch",
    "wrong_phone",
)
WITHDRAWN_KEYS = (
    "contract_form",
    "available_too_late",
    "not_looking_for_work",
    "no_contact",
    "client_refused",
)

# ORDER BY: remis kolejności rozstrzyga `id`, więc to on ustala kolejność
# nowych powodów na liście. „Inne” szukamy w tej samej kategorii co powód.
SEED_CLOSE_REASON_DICTIONARY = (
    "WITH marker AS ("
    "INSERT INTO app_settings (key, value) "
    "VALUES ('close_reason_dictionary_seeded', 'true'::jsonb) "
    "ON CONFLICT (key) DO NOTHING RETURNING key) "
    "INSERT INTO rejection_reasons "
    '(template_id, name, category, "order", active, disqualifies_person, '
    "external_source, created_at, updated_at) "
    "SELECT t.id, k.name, k.cat::terminaltype, "
    'COALESCE((SELECT GREATEST(r."order" - 1, 0) FROM rejection_reasons r '
    "WHERE r.template_id = t.id AND r.category::text = k.cat "
    "AND r.name = 'Inne (' || k.cat || ')' LIMIT 1), 99), "
    "TRUE, k.verdict, 'manual', NOW(), NOW() "
    "FROM pipeline_templates t "
    "CROSS JOIN (VALUES "
    "(1, 'client_project_closed', 'rejected', FALSE), "
    "(2, 'client_after_deadline', 'rejected', FALSE), "
    "(3, 'overqualified', 'rejected', FALSE), "
    "(4, 'other_level_or_role', 'rejected', FALSE), "
    "(5, 'no_polish', 'rejected', TRUE), "
    "(6, 'weak_english', 'rejected', TRUE), "
    "(7, 'available_too_late', 'rejected', FALSE), "
    "(8, 'in_other_process', 'rejected', FALSE), "
    "(9, 'client_refused', 'rejected', FALSE), "
    "(10, 'outdated_cv', 'rejected', FALSE), "
    "(11, 'profile_mismatch', 'rejected', FALSE), "
    "(12, 'wrong_phone', 'rejected', FALSE), "
    "(13, 'contract_form', 'withdrawn', FALSE), "
    "(14, 'available_too_late', 'withdrawn', FALSE), "
    "(15, 'not_looking_for_work', 'withdrawn', FALSE), "
    "(16, 'no_contact', 'withdrawn', FALSE), "
    "(17, 'client_refused', 'withdrawn', FALSE)"
    ") AS k(pos, name, cat, verdict) "
    "WHERE EXISTS (SELECT 1 FROM marker) "
    "ORDER BY t.id, k.pos "
    "ON CONFLICT (template_id, name, category) DO NOTHING"
)

# Ruchy z tymi powodami wskazują je kluczem obcym: skasowanie odebrałoby
# historii powód albo wywróciło się na FK. `contract_form`, `no_contact`
# i `not_looking_for_work` w odrzuceniach są starsze (0646), więc downgrade
# zdejmuje tylko wiersze, które dołożyła ta migracja.
_NEW_ROWS = (
    "(r.category::text = 'rejected' AND r.name IN ("
    + ", ".join(f"'{k}'" for k in REJECTED_KEYS)
    + ")) OR (r.category::text = 'withdrawn' AND r.name IN ("
    + ", ".join(f"'{k}'" for k in WITHDRAWN_KEYS)
    + "))"
)
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
        RAISE EXCEPTION 'Downgrade 0745 odmawia: są wpisy z powodami ze słownika.';
    END IF;
END $$"""


def upgrade() -> None:
    op.execute(SEED_CLOSE_REASON_DICTIONARY)
    # Klucz słownika jest też powodem dla systemu: więz ma jedno źródło
    # (`autofill_feedback_schema.py`), entrypoint wykonuje go przy każdym starcie.
    for stmt in schema.REASON_CHECK_DDL:
        op.execute(stmt)


def downgrade() -> None:
    # Więz powodów dla systemu zostaje szerszy, jak w 0717: wiersze z nowymi
    # powodami nie tracą danych.
    op.execute(REFUSE_WITH_LIVE_ROWS)
    op.execute(f"DELETE FROM rejection_reasons r WHERE {_NEW_ROWS}")
    op.execute("DELETE FROM app_settings WHERE key = 'close_reason_dictionary_seeded'")
