"""Domyślny szablon dostaje kolumnę dla etapu `interview`.

Szablon „Default B2B" (`pipeline_templates.is_default`) — ten, którego używa
większość rekrutacji — NIE MA kolumny zmapowanej na legacy `interview`, a to
trzeci co do wielkości etap w systemie (2 967 pierwszych osiągnięć w 2026,
1 633 kandydatów stoi na nim w tej chwili). Karty z tego etapu nie miały gdzie
się wyrenderować.

Naprawa jest wyprowadzona z SZABLONU IMPORTOWANEGO Z TRAFFITA, nie zgadnięta:
tamten ma kolumnę o **dokładnie tej samej nazwie** („Przepuszczony przez DZ")
zmapowaną na `interview`. Migracja wyrównuje szablon domyślny do już
ustalonego mapowania dla identycznie nazwanego etapu.

Trzy świadome ograniczenia:

* **Warunkowo** — rusza wyłącznie wiersze, które nadal mają
  `legacy_enum_value IS NULL`. Ręczna korekta wykonana wcześniej wygrywa.
* **Dokładnie jedna kolumna na wartość legacy w obrębie szablonu.**
  `get_kanban` buduje `enum_to_def` jako słownik, więc druga kolumna z tą samą
  wartością wygrywałaby zależnie od kolejności — czyli karty lądowałyby raz
  tu, raz tam. Dlatego `NOT EXISTS`.
* **Bez dodawania kolumny.** Szablon ma 15 kolumn, a front przełącza układ
  desktopowy na „scroll" powyżej piętnastu (`fullPipelineDesktop`). Szesnasta
  kolumna zamieniłaby bugfix w regresję układu na ~3 950 rekrutacjach.

Reguła, nie lista ID: dopasowanie idzie po nazwie kolumny i po tym, że szablon
jest domyślny. Lustro w `backend/entrypoint.sh` — prod alembic bywa osierocony.

Revision ID: 0271_default_template_interview
Revises: 0270_jobs_open_state_dates
Create Date: 2026-09-03
"""

from alembic import op


revision = "0271_default_template_interview"
down_revision = "0270_jobs_open_state_dates"
branch_labels = None
depends_on = None


# Nazwa kolumny, którą szablon importowany z Traffita mapuje na `interview`.
_INTERVIEW_COLUMN_NAME = "Przepuszczony przez DZ"

UPGRADE_SQL = f"""
    UPDATE pipeline_stage_defs AS sd
       SET legacy_enum_value = 'interview',
           updated_at = NOW()
      FROM pipeline_templates AS t
     WHERE t.id = sd.template_id
       AND t.is_default IS TRUE
       AND sd.name = '{_INTERVIEW_COLUMN_NAME}'
       AND sd.legacy_enum_value IS NULL
       AND NOT EXISTS (
           SELECT 1
             FROM pipeline_stage_defs other
            WHERE other.template_id = sd.template_id
              AND other.legacy_enum_value = 'interview'
       )
"""

# Cofnięcie zdejmuje mapowanie wyłącznie z tej jednej kolumny domyślnego
# szablonu — nie dotyka szablonów importowanych, które miały je od zawsze.
DOWNGRADE_SQL = f"""
    UPDATE pipeline_stage_defs AS sd
       SET legacy_enum_value = NULL,
           updated_at = NOW()
      FROM pipeline_templates AS t
     WHERE t.id = sd.template_id
       AND t.is_default IS TRUE
       AND sd.name = '{_INTERVIEW_COLUMN_NAME}'
       AND sd.legacy_enum_value = 'interview'
"""


def upgrade() -> None:
    op.execute(UPGRADE_SQL)


def downgrade() -> None:
    op.execute(DOWNGRADE_SQL)
