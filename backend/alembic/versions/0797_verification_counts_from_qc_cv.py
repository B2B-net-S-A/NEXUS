"""Weryfikacja liczy się od wejścia pary na „QC CV” albo dalej.

Revision ID: 0797_verification_counts_from_qc_cv
Revises: 0796_screening_return_bells

Decyzja Artura 27.11.2026. Do tej daty statystyki, cele i Liga liczyły
weryfikację w chwili przesunięcia karty na „Zweryfikowany”, także wtedy, gdy
para nigdy nie dostała CV firmowego. Listopad na produkcji: 1031 weryfikacji,
z czego 923 doszły do QC CV; 108 dalej stoi w „Zweryfikowanym”.

Teraz kamień milowy ``verified`` w ``analytics_first_milestones`` jest
pierwszym wejściem pary na kolumnę QC CV albo dowolną dalszą (CV wysłane,
Rozmowa u klienta, Akceptacja i umowa, Zatrudniony) PO zaakceptowanej
weryfikacji. Data kamienia to to wejście, autor i ``candidate_stage_id``
zostają z wiersza weryfikacji, więc zasługa idzie do tej samej osoby co
dotąd. Para bez wejścia na QC CV nie ma weryfikacji.

Kolumnę QC CV poznaje się po NAZWIE etapu (kod bywa ``interview``, a u
Nordei „Wysłać do Cpro” ma kod ``new``). Kolumna generowana
``pipeline_stage_defs.board_reach`` (funkcja ``stage_def_board_reach``) niesie
część reguły zależną od nazwy: ``later`` (QC CV albo dalej), ``closed``
(rezerwa), ``terminal`` albo NULL (decyduje kod ruchu). Razem z kodem ruchu
to lustro ``board_column_for`` (``services/board_stage_badges.py``)
i ``placeStage`` we froncie — pilnuje
``tests/test_verification_from_qc_cv_db.py`` na
``frontend/src/lib/__fixtures__/board-stage-cases.json``.

Lustro w ``entrypoint.sh`` (alembic na produkcji bywa osierocony).
"""

from alembic import op

revision = "0797_verification_counts_from_qc_cv"
down_revision = "0796_screening_return_bells"
branch_labels = None
depends_on = None

CREATE_FUNCTION = """CREATE OR REPLACE FUNCTION stage_def_board_reach(
        stage_name text, terminal_category boolean, hired_terminal boolean
    ) RETURNS text
    LANGUAGE sql IMMUTABLE PARALLEL SAFE
    AS $fn$
        SELECT CASE
            WHEN n.qc AND NOT COALESCE(terminal_category, FALSE) THEN 'later'
            WHEN NOT n.qc AND (
                n.v LIKE '%umowa podpis%' OR n.v LIKE '%umowa wysl%'
                OR n.v LIKE '%po interview%' OR n.v LIKE '%po rozmowie%'
                OR n.v LIKE '%prep%' OR n.v LIKE '%pre-interview%'
                OR n.v LIKE '%przygotowany do spotkania%'
                OR n.v LIKE '%onboarding%'
            ) THEN 'later'
            WHEN n.v LIKE '%rezerw%' THEN 'closed'
            WHEN hired_terminal THEN 'later'
            WHEN terminal_category THEN 'terminal'
        END
        FROM (
            SELECT s.v,
                   (s.v ~ '[[:<:]](dz|qc|cpro)[[:>:]]'
                    OR s.v LIKE '%przepuszcz%') AS qc
            FROM (
                SELECT btrim(translate(
                    lower(COALESCE(stage_name, '')),
                    'ąćęłńóśźż', 'acelnoszz'
                )) AS v
            ) s
        ) n
    $fn$"""

# Liczona raz na etap szablonu, nie na każdy ruch: wyrażenie regularne
# w widoku dla każdego wiersza `candidate_stages` robiło go 40× wolniejszym
# (kopia produkcji 27.11.2026: 1,16 s zamiast 0,03 s; z kolumną 0,1 s).
ADD_COLUMN = """ALTER TABLE pipeline_stage_defs ADD COLUMN IF NOT EXISTS board_reach text
    GENERATED ALWAYS AS (stage_def_board_reach(name, category = 'terminal', terminal_type = 'hired')) STORED"""

CREATE_VIEW = """CREATE OR REPLACE VIEW analytics_first_milestones AS
        SELECT
            ranked.candidate_id,
            ranked.job_id,
            ranked.stage,
            CASE WHEN ranked.stage = 'verified' THEN qc.reached_at
                 ELSE ranked.moved_at END AS first_reached_at,
            ranked.moved_by AS first_moved_by,
            ranked.id AS candidate_stage_id
        FROM (
            SELECT
                cs.candidate_id,
                cs.job_id,
                cs.stage,
                cs.moved_at,
                cs.moved_by,
                cs.id,
                ROW_NUMBER() OVER (
                    PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                    ORDER BY cs.moved_at ASC, cs.id ASC
                ) AS rn
            FROM candidate_stages cs
            WHERE cs.stage IN (
                'verified', 'cv_sent', 'interview', 'client_interview',
                'acceptance', 'hired'
            )
            -- Odrzucone/oczekujące weryfikacje NIE liczą się jako kamień
            -- milowy ani nie kotwiczą kredytu (M7-P0.8). Liczy się tylko
            -- zaakceptowana ('active') weryfikacja. Pozostałe stage'y mają
            -- default verification_status='active', więc filtr ich nie dotyka.
            AND (cs.stage <> 'verified' OR cs.verification_status = 'active')
            -- 0343: „Zatrudniony" wykluczonej pary (seria bez CV, patrz
            -- app/services/placement_exclusions.py) nie jest placementem.
            -- Tabela `placement_exclusions` powstaje instrukcję wyżej.
            AND (
                cs.stage <> 'hired'
                OR NOT EXISTS (
                    SELECT 1 FROM placement_exclusions pe
                    WHERE pe.candidate_id = cs.candidate_id
                      AND pe.job_id = cs.job_id
                )
            )
        ) ranked
        -- 0797: weryfikacja liczy się w dniu pierwszego wejścia pary na
        -- QC CV albo dalej, po pierwszej zaakceptowanej weryfikacji (decyzja
        -- Artura 27.11.2026). Rodzaj etapu z nazwy to `board_reach`.
        LEFT JOIN (
            SELECT first_verified.candidate_id, first_verified.job_id,
                   min(later.moved_at) AS reached_at
            FROM (
                SELECT candidate_id, job_id, min(moved_at) AS verified_at
                FROM candidate_stages
                WHERE stage = 'verified' AND verification_status = 'active'
                GROUP BY candidate_id, job_id
            ) first_verified
            JOIN candidate_stages later
              ON later.candidate_id = first_verified.candidate_id
             AND later.job_id = first_verified.job_id
             AND later.moved_at >= first_verified.verified_at
            LEFT JOIN pipeline_stage_defs sd ON sd.id = later.stage_def_id
            WHERE (sd.board_reach = 'later' OR (later.stage::text = 'hired' AND sd.board_reach IS DISTINCT FROM 'closed') OR (sd.board_reach IS NULL AND later.stage::text IN ('cv_sent', 'client_interview', 'acceptance', 'negotiation', 'onboarding')))
            GROUP BY first_verified.candidate_id, first_verified.job_id
        ) qc ON ranked.stage = 'verified'
            AND qc.candidate_id = ranked.candidate_id
            AND qc.job_id = ranked.job_id
        WHERE rn = 1
          AND (ranked.stage <> 'verified' OR qc.reached_at IS NOT NULL)"""

PREVIOUS_VIEW = """CREATE OR REPLACE VIEW analytics_first_milestones AS
        SELECT
            candidate_id,
            job_id,
            stage,
            moved_at AS first_reached_at,
            moved_by AS first_moved_by,
            id AS candidate_stage_id
        FROM (
            SELECT
                cs.candidate_id,
                cs.job_id,
                cs.stage,
                cs.moved_at,
                cs.moved_by,
                cs.id,
                ROW_NUMBER() OVER (
                    PARTITION BY cs.candidate_id, cs.job_id, cs.stage
                    ORDER BY cs.moved_at ASC, cs.id ASC
                ) AS rn
            FROM candidate_stages cs
            WHERE cs.stage IN (
                'verified', 'cv_sent', 'interview', 'client_interview',
                'acceptance', 'hired'
            )
            AND (cs.stage <> 'verified' OR cs.verification_status = 'active')
            AND (
                cs.stage <> 'hired'
                OR NOT EXISTS (
                    SELECT 1 FROM placement_exclusions pe
                    WHERE pe.candidate_id = cs.candidate_id
                      AND pe.job_id = cs.job_id
                )
            )
        ) ranked
        WHERE rn = 1"""


def upgrade() -> None:
    op.execute(CREATE_FUNCTION)
    op.execute(ADD_COLUMN)
    op.execute(CREATE_VIEW)


def downgrade() -> None:
    op.execute(PREVIOUS_VIEW)
    op.execute("ALTER TABLE pipeline_stage_defs DROP COLUMN IF EXISTS board_reach")
    op.execute("DROP FUNCTION IF EXISTS stage_def_board_reach(text, boolean, boolean)")
